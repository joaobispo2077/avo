# Installed Watch Skill boundary with structured AVO review evidence.

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avo.adapters.base import JobRequest, JobResult
from avo.adapters.understand.watch_policy import (
    DEFAULT_WATCH_SETTINGS,
    build_watch_prompt,
)
from avo.timeline.ports import ToolError

_BONSAI_OPTION_IDS = frozenset({"bonsai-27b-gguf", "ternary-bonsai-27b-gguf"})


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _require_bonsai_runtime(option_id: str) -> None:
    """Fail closed when a Bonsai understand pin lacks GGUF, mmproj, or custom vision."""
    if option_id not in _BONSAI_OPTION_IDS:
        return
    gguf = (os.environ.get("AVO_UNDERSTAND_GGUF") or "").strip()
    if not gguf or not Path(gguf).is_file():
        raise ToolError(
            "WATCH_UNAVAILABLE",
            "Bonsai GGUF is not ready: set AVO_UNDERSTAND_GGUF to an existing file from "
            "prism-ml/Bonsai-27B-gguf (or the ternary sibling) before Watch review.",
            True,
            "download the language GGUF, set AVO_UNDERSTAND_GGUF, then retry",
        )
    mmproj = (os.environ.get("AVO_UNDERSTAND_MMPROJ") or "").strip()
    if not mmproj or not Path(mmproj).is_file():
        raise ToolError(
            "WATCH_UNAVAILABLE",
            "Watch needs the Bonsai vision mmproj alongside the language GGUF.",
            True,
            "set AVO_UNDERSTAND_MMPROJ to the vision mmproj path and retry",
        )
    custom_url = (os.environ.get("WATCHSKILL_CUSTOM_BASE_URL") or "").strip()
    cheap = (os.environ.get("WATCHSKILL_VISION_CHEAP_PROVIDER") or "").strip()
    strong = (os.environ.get("WATCHSKILL_VISION_STRONG_PROVIDER") or "").strip()
    if not custom_url and cheap != "custom" and strong != "custom":
        raise ToolError(
            "WATCH_UNAVAILABLE",
            "Bonsai understand pin only after llama.cpp custom vision is up "
            "(WATCHSKILL_CUSTOM_BASE_URL or WATCHSKILL_VISION_*_PROVIDER=custom).",
            True,
            "start llama-server with GGUF+mmproj, run watch-skill setup-vision --provider custom, then retry",
        )


def _bundled_executable() -> str | None:
    root = _repository_root()
    candidates = [
        root / "tools" / "watch-skill" / ".venv" / "bin" / "watch-skill",
        root / "tools" / "watch-skill" / ".venv" / "Scripts" / "watch-skill.exe",
    ]
    return str(next((path for path in candidates if path.is_file()), "")) or None


_VALID_WATCH_STATUS = frozenset({"pass", "fail", "needs-human-judgment"})
_REFUSAL_MARKERS = (
    "No guess is being made",
    "does not clearly show an answer",
)


def _refusal_analysis(text: str) -> dict[str, Any] | None:
    if not any(marker in text for marker in _REFUSAL_MARKERS):
        return None
    return {
        "status": "needs-human-judgment",
        "confidence": 0.0,
        "findings": [
            {
                "classification": "meaning",
                "severity": "warning",
                "message": (
                    "Watch retrieval/vision did not produce a structured cut-proof "
                    "analysis; human must inspect the exact candidate."
                ),
                "start": None,
                "end": None,
            }
        ],
        "model": "watch-skill-refusal",
    }


def _iter_json_objects(text: str) -> list[dict[str, Any]]:
    candidates = re.findall(
        r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE
    )
    candidates.extend(text[index:] for index, char in enumerate(text) if char == "{")
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            value, _ = decoder.raw_decode(candidate.strip())
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects


def _extract_json_object(text: str) -> dict[str, Any]:
    for value in reversed(_iter_json_objects(text)):
        if str(value.get("status") or "") in _VALID_WATCH_STATUS:
            return value
    raise ValueError("Watch analysis did not return a JSON object")


@dataclass(frozen=True)
class _ReviewRequest:
    candidate: Path
    scope: str
    windows: list[dict[str, Any]]
    policy_payload: dict[str, Any]
    effective: dict[str, Any]
    artifact_dir: Path
    checkpoint: str
    context: dict[str, Any]
    prompt: str
    root: Path
    watch_env: dict[str, str]
    transcript_ref: str | Path | None
    terms: list[str]
    names: list[str]


@dataclass(frozen=True)
class _AnalysisRun:
    analysis: dict[str, Any]
    result: JobResult
    attempts: list[dict[str, Any]]


def _option_id(requested: Any) -> str:
    if requested is not None:
        return str(requested or "")
    try:
        from avo.models import resolve_option_id

        return str(resolve_option_id("understand", root=_repository_root()) or "")
    except Exception:
        return ""


def _request_value(request: dict[str, Any], key: str, default: Any) -> Any:
    return request.get(key) or default


def _policy_settings(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = dict(request.get("policy") or {})
    configured = dict(payload.get("effective") or payload)
    return payload, {**DEFAULT_WATCH_SETTINGS, **configured}


def _artifact_directory(candidate: Path, request: dict[str, Any]) -> Path:
    default = Path(_request_value(request, "root", candidate.parent)) / ".avo-watch"
    directory = Path(_request_value(request, "artifact_dir", default))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _working_root(
    candidate: Path, request: dict[str, Any], effective: dict[str, Any]
) -> Path:
    configured = effective.get("workingDirectory")
    return Path(configured or _request_value(request, "root", candidate.parent))


def _watch_environment(effective: dict[str, Any]) -> dict[str, str]:
    if effective.get("device") == "cpu":
        return {"CUDA_VISIBLE_DEVICES": "-1"}
    return {}


def _review_request(candidate: Path, request: dict[str, Any]) -> _ReviewRequest:
    scope = str(_request_value(request, "scope", "full"))
    windows = list(_request_value(request, "windows", []))
    policy_payload, effective = _policy_settings(request)
    artifact_dir = _artifact_directory(candidate, request)
    checkpoint = str(_request_value(request, "checkpoint", "cut-proof"))
    context = dict(_request_value(request, "context", {}))
    transcript_ref = request.get("transcript_ref")
    terms = list(_request_value(request, "terms", []))
    names = list(_request_value(request, "names", []))
    prompt = build_watch_prompt(
        checkpoint=checkpoint,
        scope=scope,
        windows=windows,
        context=context,
        transcript_ref=transcript_ref,
        terms=terms,
        names=names,
    )
    return _ReviewRequest(
        candidate=candidate,
        scope=scope,
        windows=windows,
        policy_payload=policy_payload,
        effective=effective,
        artifact_dir=artifact_dir,
        checkpoint=checkpoint,
        context=context,
        prompt=prompt,
        root=_working_root(candidate, request, effective),
        watch_env=_watch_environment(effective),
        transcript_ref=transcript_ref,
        terms=terms,
        names=names,
    )


def _window_timestamps(windows: list[dict[str, Any]]) -> list[float]:
    timestamps = {
        timestamp
        for window in windows
        for timestamp in (
            float(window["start"]),
            (float(window["start"]) + float(window["end"])) / 2,
            float(window["end"]),
        )
    }
    return sorted(timestamps)


def _watch_argv(review: _ReviewRequest) -> list[str]:
    argv = [
        "watch",
        str(review.candidate),
        review.prompt,
        "--out-dir",
        str(review.artifact_dir),
        "--index",
        "--whisper-model",
        str(review.effective["whisperModel"]),
    ]
    timestamps = _window_timestamps(review.windows)
    if timestamps:
        argv.extend(["--timestamps", ",".join(f"{value:.3f}" for value in timestamps)])
    return argv


def _acquire_candidate(adapter: Any, review: _ReviewRequest) -> tuple[JobResult, str]:
    watched = adapter.run(
        JobRequest(
            job="understand",
            label=f"Watch {review.candidate.name}",
            argv=_watch_argv(review),
            root=review.root,
            env=review.watch_env,
        )
    )
    if watched.exit_code != 0:
        raise adapter._tool_error(watched, "acquisition")
    match = re.search(r"video_id\s+`([^`]+)`", watched.stdout)
    if not match:
        raise ToolError(
            "WATCH_MALFORMED",
            "Watch acquisition did not return an indexed video id",
            True,
            "retry Watch on the exact candidate; if repeated, run watch-skill doctor",
        )
    return watched, match.group(1)


def _attempt_prompt(review: _ReviewRequest, attempt: int) -> str:
    if attempt == 1:
        return review.prompt
    return build_watch_prompt(
        checkpoint=review.checkpoint,
        scope=review.scope,
        windows=review.windows,
        context=review.context,
        transcript_ref=review.transcript_ref,
        terms=review.terms,
        names=review.names,
        repair=True,
    )


def _ask_argv(review: _ReviewRequest, video_id: str, attempt: int) -> list[str]:
    frame_key = "maxFrames" if attempt == 1 else "repairMaxFrames"
    return [
        "ask",
        video_id,
        _attempt_prompt(review, attempt),
        "--frames",
        "--no-cache",
        "--max-frames",
        str(review.effective[frame_key]),
    ]


def _attempt_record(attempt: int, result: JobResult) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "exitCode": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _analysis_from_output(text: str) -> dict[str, Any] | None:
    try:
        return _extract_json_object(text)
    except ValueError:
        return _refusal_analysis(text)


def _analyze_candidate(
    adapter: Any, review: _ReviewRequest, video_id: str
) -> _AnalysisRun:
    attempts: list[dict[str, Any]] = []
    latest = JobResult(exit_code=0)
    for attempt in range(1, int(review.effective["analysisAttempts"]) + 1):
        latest = adapter.run(
            JobRequest(
                job="understand",
                label=f"Analyze {review.candidate.name}",
                argv=_ask_argv(review, video_id, attempt),
                root=review.root,
                env=review.watch_env,
            )
        )
        attempts.append(_attempt_record(attempt, latest))
        if latest.exit_code != 0:
            raise adapter._tool_error(latest, "analysis")
        analysis = _analysis_from_output(latest.stdout)
        if analysis is not None:
            return _AnalysisRun(analysis=analysis, result=latest, attempts=attempts)
    raise ToolError(
        "WATCH_MALFORMED",
        "Watch analysis did not return a schema-valid JSON object",
        True,
        "retry the exact candidate; repeated malformed output blocks the gate",
    )


def _validated_analysis(analysis: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    status = str(analysis.get("status") or "")
    if status not in _VALID_WATCH_STATUS:
        raise ToolError(
            "WATCH_MALFORMED",
            f"invalid Watch analysis status: {status!r}",
            True,
            "retry the exact candidate with the structured-output contract",
        )
    findings = analysis.get("findings")
    if not isinstance(findings, list) or not all(
        isinstance(item, dict) for item in findings
    ):
        raise ToolError(
            "WATCH_MALFORMED",
            "Watch analysis findings must be a list of objects",
            True,
            "retry the exact candidate with the structured-output contract",
        )
    return status, findings


def _write_raw_artifacts(
    review: _ReviewRequest,
    watched: JobResult,
    attempts: list[dict[str, Any]],
) -> tuple[Path, Path]:
    analysis_path = review.artifact_dir / "watch-analysis.txt"
    analysis_path.write_text(
        "\n\n".join(
            f"--- attempt {item['attempt']} ---\n{item['stdout']}" for item in attempts
        ),
        encoding="utf-8",
    )
    report_path = review.artifact_dir / "watch-report.md"
    report_path.write_text(watched.stdout, encoding="utf-8")
    return report_path, analysis_path


def _evidence_payload(
    adapter: Any,
    review: _ReviewRequest,
    analysis_run: _AnalysisRun,
    report_path: Path,
    analysis_path: Path,
) -> dict[str, Any]:
    status, findings = _validated_analysis(analysis_run.analysis)
    return {
        "schemaVersion": "1.0.0",
        "status": status,
        "checkpoint": review.checkpoint,
        "candidate": str(review.candidate),
        "coverage": {
            "mode": "full" if review.scope in {"full", "whole"} else "windows",
            "windows": review.windows,
        },
        "findings": findings,
        "confidence": analysis_run.analysis.get("confidence"),
        "tool": "watch-skill",
        "toolVersion": adapter.tool_version(),
        "model": analysis_run.analysis.get("model"),
        "outcomeKind": (
            "uncertainty" if status == "needs-human-judgment" else "content"
        ),
        "policy": {
            "effective": review.effective,
            "sources": dict(review.policy_payload.get("sources") or {}),
            "policyHash": review.policy_payload.get("policyHash"),
        },
        "reviewContext": review.context,
        "promptSha256": hashlib.sha256(review.prompt.encode("utf-8")).hexdigest(),
        "attempts": analysis_run.attempts,
        "rawReport": str(report_path),
        "rawAnalysis": str(analysis_path),
    }


def _write_evidence(review: _ReviewRequest, payload: dict[str, Any]) -> Path:
    evidence_path = review.artifact_dir / "watch-evidence.json"
    evidence_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence_path


class WatchSkillAdapter:
    routing_id = "watch-skill"

    def __init__(self, executable: str | None = None):
        self.executable = (
            executable
            or os.environ.get("WATCH_SKILL_BIN")
            or _bundled_executable()
            or shutil.which("watch-skill")
            or "watch-skill"
        )

    @staticmethod
    def validate_coverage(scope: str, windows: list[dict[str, Any]]) -> None:
        if scope in {"targeted", "windows"} and not windows:
            raise ValueError("targeted Watch review requires changed/risk windows")

    def run(self, request: JobRequest) -> JobResult:
        environment = os.environ.copy()
        environment.update(request.env)
        try:
            completed = subprocess.run(
                [self.executable, *request.argv],
                cwd=request.root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as error:
            return JobResult(exit_code=2, stderr=f"watch-skill unavailable: {error}")
        stdout = completed.stdout or ""
        artifacts = [
            Path(line.strip())
            for line in stdout.splitlines()
            if line.strip().endswith((".json", ".md", ".html"))
            and Path(line.strip()).exists()
        ]
        return JobResult(
            exit_code=completed.returncode,
            artifact_paths=artifacts,
            stdout=stdout,
            stderr=completed.stderr or "",
        )

    def tool_version(self) -> str:
        result = self.run(
            JobRequest(
                job="understand",
                label="Watch version",
                argv=["version"],
                root=_repository_root(),
            )
        )
        return (
            result.stdout.strip().splitlines()[0]
            if result.exit_code == 0 and result.stdout.strip()
            else "unknown"
        )

    @staticmethod
    def _tool_error(result: JobResult, phase: str) -> ToolError:
        return ToolError(
            "WATCH_UNAVAILABLE",
            result.stderr or result.stdout or f"Watch {phase} failed",
            True,
            "run watch-skill doctor, repair the local tool/model, and retry the same candidate",
        )

    def review(self, candidate: Path, **request: Any) -> dict[str, Any]:
        candidate = Path(candidate)
        self.validate_coverage(
            str(_request_value(request, "scope", "full")),
            list(_request_value(request, "windows", [])),
        )
        _require_bonsai_runtime(_option_id(request.get("option_id")))
        review = _review_request(candidate, request)
        watched, video_id = _acquire_candidate(self, review)
        analysis_run = _analyze_candidate(self, review, video_id)
        report_path, analysis_path = _write_raw_artifacts(
            review, watched, analysis_run.attempts
        )
        payload = _evidence_payload(
            self, review, analysis_run, report_path, analysis_path
        )
        evidence_path = _write_evidence(review, payload)
        return {
            **payload,
            "artifacts": [
                str(report_path),
                str(analysis_path),
                str(evidence_path),
                *[
                    str(path)
                    for path in watched.artifact_paths
                    + analysis_run.result.artifact_paths
                ],
            ],
        }
