# Installed Watch Skill boundary with structured AVO review evidence.

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import urllib.request
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from avo.adapters.base import JobRequest, JobResult
from avo.adapters.understand.watch_policy import (
    DEFAULT_WATCH_SETTINGS,
    build_watch_prompt,
)
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.cutting_contracts import source_interval
from avo.timeline.ports import ToolError
from avo.timeline.vision_review import (
    VisionReviewError,
    build_capability_snapshot,
    compile_review_coverage,
    validate_vision_finding,
)

_BONSAI_OPTION_IDS = frozenset({"bonsai-27b-gguf", "ternary-bonsai-27b-gguf"})


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _dict_at(node: Any, key: str) -> dict[str, Any]:
    value = node.get(key) if isinstance(node, dict) else None
    return value if isinstance(value, dict) else {}


def _env_or(pin_value: Any, env_key: str) -> str:
    return str(pin_value or os.environ.get(env_key) or "").strip()


def _bonsai_paths(pin: dict[str, Any] | None) -> tuple[str, str, str]:
    source = _dict_at(pin, "source")
    companion = _dict_at(source, "companion")
    endpoint = _dict_at(source, "endpoint")
    return (
        _env_or(source.get("artifactPath"), "AVO_UNDERSTAND_GGUF"),
        _env_or(companion.get("mmproj"), "AVO_UNDERSTAND_MMPROJ"),
        _env_or(endpoint.get("baseUrl"), "WATCHSKILL_CUSTOM_BASE_URL"),
    )


def _missing_file(path: str) -> bool:
    return not path or not Path(path).is_file()


def _require_bonsai_runtime(option_id: str, pin: dict[str, Any] | None = None) -> None:
    """Fail closed when a Bonsai understand pin lacks GGUF, mmproj, or custom vision."""
    if option_id not in _BONSAI_OPTION_IDS:
        return
    gguf, mmproj, custom_url = _bonsai_paths(pin)
    if _missing_file(gguf):
        raise ToolError(
            "WATCH_UNAVAILABLE",
            "Bonsai GGUF is not ready: set AVO_UNDERSTAND_GGUF to an existing file from "
            "prism-ml/Bonsai-27B-gguf (or the ternary sibling) before Watch review.",
            True,
            "download the language GGUF, set AVO_UNDERSTAND_GGUF, then retry",
        )
    if _missing_file(mmproj):
        raise ToolError(
            "WATCH_UNAVAILABLE",
            "Watch needs the Bonsai vision mmproj alongside the language GGUF.",
            True,
            "set AVO_UNDERSTAND_MMPROJ to the vision mmproj path and retry",
        )
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
    win = [
        root / "tools" / "watch-skill" / ".venv-win" / "Scripts" / "watch-skill.exe",
        root / "tools" / "watch-skill" / ".venv" / "Scripts" / "watch-skill.exe",
    ]
    posix = [root / "tools" / "watch-skill" / ".venv" / "bin" / "watch-skill"]
    candidates = win + posix if os.name == "nt" else posix + win
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
    contract_context: dict[str, Any]


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


def _watch_environment(
    effective: dict[str, Any], model_pin: dict[str, Any] | None = None
) -> dict[str, str]:
    environment: dict[str, str] = {}
    if effective.get("device") == "cpu":
        environment.update({"CUDA_VISIBLE_DEVICES": "-1"})
    source = _dict_at(model_pin, "source")
    endpoint = _dict_at(source, "endpoint")
    base_url = str(endpoint.get("baseUrl") or "").strip()
    served_name = str(endpoint.get("servedName") or "").strip()
    if source.get("kind") == "endpoint" and base_url and served_name:
        environment.update(
            {
                "WATCHSKILL_VISION_CHEAP_PROVIDER": "custom",
                "WATCHSKILL_VISION_CHEAP_MODEL": served_name,
                "WATCHSKILL_VISION_STRONG_PROVIDER": "custom",
                "WATCHSKILL_VISION_STRONG_MODEL": served_name,
                "WATCHSKILL_CUSTOM_BASE_URL": base_url,
            }
        )
        api_key = (os.environ.get("WATCHSKILL_CUSTOM_API_KEY") or "").strip()
        if api_key:
            environment["WATCHSKILL_CUSTOM_API_KEY"] = api_key
        elif base_url.startswith(("http://127.0.0.1", "http://localhost")):
            environment["WATCHSKILL_CUSTOM_API_KEY"] = "lm-studio"
    return environment


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
        watch_env=_watch_environment(effective, request.get("model_pin")),
        transcript_ref=transcript_ref,
        terms=terms,
        names=names,
        contract_context=dict(request.get("contract_context") or {}),
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
        return None


def _unstructured_analysis(text: str) -> dict[str, Any] | None:
    blob = text.strip()
    if not blob:
        return None
    excerpt = " ".join(blob.split())
    if len(excerpt) > 280:
        excerpt = excerpt[:277] + "..."
    return {
        "status": "needs-human-judgment",
        "confidence": 0.0,
        "findings": [
            {
                "classification": "meaning",
                "severity": "warning",
                "message": (
                    "Watch returned retrieval/vision prose instead of schema JSON "
                    f"({excerpt}); human must inspect the exact candidate."
                ),
                "start": None,
                "end": None,
            }
        ],
        "model": "watch-skill-unstructured",
    }


def _resolved_analysis(text: str) -> dict[str, Any] | None:
    return (
        _analysis_from_output(text)
        or _refusal_analysis(text)
        or _unstructured_analysis(text)
    )


def _coverage_payload(
    review: _ReviewRequest,
    attempts: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    frame_key = "maxFrames" if len(attempts) == 1 else "repairMaxFrames"
    windows = list(review.windows)
    return {
        "mode": ("full" if review.scope in {"full", "whole"} else "sampled"),
        "sampling": "frames",
        "windows": list(analysis.get("observedWindows") or []),
        "requestedScope": review.scope,
        "requestedWindows": windows,
        "requestedFrames": list(analysis.get("requestedFrames") or []),
        "decodedFrames": list(analysis.get("decodedFrames") or []),
        "failedFrames": list(analysis.get("failedFrames") or []),
        "observedFrames": list(analysis.get("observedFrames") or []),
        "inspectedRanges": list(analysis.get("inspectedRanges") or []),
        "partiallyInspectedRanges": list(
            analysis.get("partiallyInspectedRanges") or []
        ),
        "deterministicallyCheckedRanges": list(
            analysis.get("deterministicallyCheckedRanges") or []
        ),
        "coverageHoles": list(analysis.get("coverageHoles") or []),
        "maxFrames": int(review.effective[frame_key]),
    }


def _coerce_findings(raw: Any) -> list[dict[str, Any]] | None:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw] if raw.strip() else []
    if not isinstance(raw, list):
        return None
    findings: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            findings.append(item)
        elif isinstance(item, str):
            findings.append(
                {
                    "classification": "technical",
                    "severity": "warning",
                    "message": item,
                }
            )
        else:
            return None
    return findings


def _is_retrieval_refusal(text: str) -> bool:
    return "does not clearly show an answer" in text or "No guess is being made" in text


def _analyze_candidate(
    adapter: Any, review: _ReviewRequest, video_id: str
) -> _AnalysisRun:
    attempts: list[dict[str, Any]] = []
    latest = JobResult(exit_code=0)
    limit = int(review.effective["analysisAttempts"])
    for attempt in range(1, limit + 1):
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
        analysis = _resolved_analysis(latest.stdout)
        if analysis is None:
            continue
        if (
            attempt < limit
            and analysis.get("model")
            in {"watch-skill-unstructured", "watch-skill-refusal"}
            and _is_retrieval_refusal(latest.stdout)
        ):
            continue
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
    findings = _coerce_findings(analysis.get("findings"))
    if findings is None:
        raise ToolError(
            "WATCH_MALFORMED",
            "Watch analysis findings must be a list of objects",
            True,
            "retry the exact candidate with the structured-output contract",
        )
    return status, findings


def _model_identity(result: JobResult, _analysis: dict[str, Any]) -> str | None:
    model = str(result.models_used.get("understand") or "").strip()
    return model or None


def _write_raw_artifacts(
    review: _ReviewRequest,
    watched: JobResult,
    attempts: list[dict[str, Any]],
) -> tuple[Path, Path, list[Path]]:
    raw_directory = review.artifact_dir / "raw"
    raw_directory.mkdir(parents=True, exist_ok=True)
    raw_paths: list[Path] = []
    for item in attempts:
        attempt = int(item["attempt"])
        for stream in ("stdout", "stderr"):
            path = raw_directory / f"attempt-{attempt:02d}.{stream}.txt"
            path.write_text(str(item.get(stream) or ""), encoding="utf-8")
            raw_paths.append(path)
    analysis_path = review.artifact_dir / "watch-analysis.txt"
    analysis_path.write_text(
        "\n\n".join(
            f"--- attempt {item['attempt']} stdout ---\n{item['stdout']}\n"
            f"--- attempt {item['attempt']} stderr ---\n{item['stderr']}"
            for item in attempts
        ),
        encoding="utf-8",
    )
    report_path = review.artifact_dir / "watch-report.md"
    report_path.write_text(watched.stdout, encoding="utf-8")
    raw_paths.extend(path for path in watched.artifact_paths if Path(path).is_file())
    return report_path, analysis_path, raw_paths


def _raw_artifact_ref(path: Path, *, kind: str) -> dict[str, Any]:
    data = Path(path).read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sizeBytes": len(data),
        "kind": kind,
    }


def _evidence_payload(
    adapter: Any,
    review: _ReviewRequest,
    analysis_run: _AnalysisRun,
    report_path: Path,
    analysis_path: Path,
    raw_paths: list[Path],
) -> dict[str, Any]:
    status, findings = _validated_analysis(analysis_run.analysis)
    external_paths = [
        *analysis_run.result.artifact_paths,
    ]
    raw_refs = [
        _raw_artifact_ref(path, kind="watch-raw")
        for path in [report_path, analysis_path, *raw_paths, *external_paths]
        if Path(path).is_file()
    ]
    attempts = [
        {
            "attempt": int(item["attempt"]),
            "exitCode": int(item["exitCode"]),
            "stdoutSha256": hashlib.sha256(
                str(item.get("stdout") or "").encode("utf-8")
            ).hexdigest(),
            "stderrSha256": hashlib.sha256(
                str(item.get("stderr") or "").encode("utf-8")
            ).hexdigest(),
        }
        for item in analysis_run.attempts
    ]
    return {
        "schemaVersion": "1.0.0",
        "status": status,
        "checkpoint": review.checkpoint,
        "candidate": str(review.candidate),
        "coverage": _coverage_payload(
            review, analysis_run.attempts, analysis_run.analysis
        ),
        "findings": findings,
        "confidence": analysis_run.analysis.get("confidence"),
        "tool": "watch-skill",
        "toolVersion": adapter.tool_version(),
        "model": _model_identity(analysis_run.result, analysis_run.analysis),
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
        "attempts": attempts,
        "rawArtifactRefs": raw_refs,
    }


def _write_evidence(review: _ReviewRequest, payload: dict[str, Any]) -> Path:
    evidence_path = review.artifact_dir / "watch-evidence.json"
    evidence_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence_path


def probe_vision_capabilities(
    *,
    model_pin: dict[str, Any],
    probe: Callable[[str, str], dict[str, Any]],
    resource_policy: dict[str, Any],
    conservative_context_limit: int | None = None,
) -> dict[str, Any]:
    """Probe the exact configured OpenAI-compatible endpoint and freeze identity."""
    source = _dict_at(model_pin, "source")
    endpoint = _dict_at(source, "endpoint")
    configured_model = str(model_pin.get("id") or "").strip()
    served_name = str(endpoint.get("servedName") or "").strip()
    base_url = str(endpoint.get("baseUrl") or "").strip()
    if (
        source.get("kind") != "endpoint"
        or not configured_model
        or not served_name
        or not base_url
    ):
        raise VisionReviewError("vision review requires an exact endpoint model pin")
    if served_name != configured_model:
        raise VisionReviewError("configured model pin and endpoint served name differ")
    try:
        observed = probe(base_url, served_name)
    except Exception as error:
        raise VisionReviewError(
            f"vision endpoint live probe failed: {error}"
        ) from error
    return build_capability_snapshot(
        configured_model=configured_model,
        endpoint_identity={
            "providerType": "openai-compatible",
            "redactedBase": re.sub(r"//[^/]+", "//<endpoint>", base_url),
        },
        probe=observed,
        resource_policy=resource_policy,
        conservative_context_limit=conservative_context_limit,
    )


def _retry_reduction(
    review_pass: dict[str, Any], retry_number: int
) -> tuple[dict[str, Any], str]:
    reduced = deepcopy(review_pass)
    frames = list(reduced.get("sampleFrames") or [])
    deduplicated = list(dict.fromkeys(frames))
    if deduplicated != frames:
        reduced["sampleFrames"] = deduplicated
        reduction = "deduplicate-frames"
    elif reduced.get("detail") not in {None, "low"}:
        reduced["detail"] = "low"
        reduction = "reduce-detail"
    elif int(reduced.get("transcriptHandleFrames") or 0) > 0:
        reduced["transcriptHandleFrames"] = max(
            0, int(reduced.get("transcriptHandleFrames") or 0) // 2
        )
        reduction = "reduce-transcript-handles"
    else:
        midpoint = max(1, len(frames) // 2)
        reduced["windowSegments"] = [frames[:midpoint], frames[midpoint:]]
        reduction = "split-window"
    required = set(review_pass.get("requiredFrames") or [])
    if not required.issubset(set(reduced.get("sampleFrames") or [])):
        raise VisionReviewError("bounded retry would drop mandatory coverage")
    return reduced, reduction


def execute_bounded_passes(
    *,
    candidate_index: str,
    passes: list[dict[str, Any]],
    capability_snapshot: dict[str, Any],
    invoke: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Execute bounded passes against one index and one verified served model."""
    expected_model = str(capability_snapshot.get("servedModel") or "")
    if not candidate_index or not expected_model:
        raise VisionReviewError(
            "candidate index and verified served model are required"
        )
    pass_results: list[dict[str, Any]] = []
    requested: list[int] = []
    decoded: list[int] = []
    failed: list[int] = []
    observed: list[int] = []
    for original in passes:
        current = deepcopy(original)
        max_attempts = max(1, int(current.get("maxAttempts") or 1))
        retry_history: list[dict[str, Any]] = []
        response: dict[str, Any] = {}
        for attempt in range(1, max_attempts + 1):
            response = invoke(candidate_index, deepcopy(current))
            response_model = str(response.get("model") or "")
            if response_model != expected_model:
                raise VisionReviewError(
                    f"review model {response_model!r} does not match verified model {expected_model!r}"
                )
            response_identity = response.get("capabilityIdentityHash")
            if (
                response_identity is not None
                and response_identity != capability_snapshot.get("identityHash")
            ):
                raise VisionReviewError(
                    "review endpoint capability identity changed during execution"
                )
            if response.get("lifecycleActions"):
                raise VisionReviewError(
                    "review attempted to manage the operator-owned model lifecycle"
                )
            if response.get("status") in {"pass", "fail", "needs-human-judgment"}:
                required_fields = {
                    "requestedFrames",
                    "decodedFrames",
                    "failedFrames",
                    "observedFrames",
                }
                if required_fields.issubset(response):
                    break
                response = {**response, "status": "malformed"}
            if attempt == max_attempts:
                response = {
                    **response,
                    "status": "blocked",
                    "requestedFrames": list(current.get("sampleFrames") or []),
                    "decodedFrames": [],
                    "failedFrames": list(current.get("sampleFrames") or []),
                    "observedFrames": [],
                }
                break
            current, reduction = _retry_reduction(current, attempt)
            retry_history.append(
                {
                    "attempt": attempt,
                    "trigger": response.get("status") or "malformed",
                    "reduction": reduction,
                }
            )
        requested.extend(int(frame) for frame in response["requestedFrames"])
        decoded.extend(int(frame) for frame in response["decodedFrames"])
        failed.extend(int(frame) for frame in response["failedFrames"])
        observed.extend(int(frame) for frame in response["observedFrames"])
        pass_results.append(
            {
                "passId": original["passId"],
                "status": response["status"],
                "requestedFrames": list(response["requestedFrames"]),
                "decodedFrames": list(response["decodedFrames"]),
                "failedFrames": list(response["failedFrames"]),
                "observedFrames": list(response["observedFrames"]),
                "findings": deepcopy(response.get("findings") or []),
                "retryHistory": retry_history,
                "rawArtifactRefs": deepcopy(response.get("rawArtifactRefs") or []),
            }
        )
    return {
        "candidateIndex": candidate_index,
        "model": expected_model,
        "capabilityIdentityHash": capability_snapshot.get("identityHash"),
        "passResults": pass_results,
        "requestedSamples": list(dict.fromkeys(requested)),
        "decodedSamples": list(dict.fromkeys(decoded)),
        "failedSamples": list(dict.fromkeys(failed)),
        "observedSamples": list(dict.fromkeys(observed)),
    }


def _native_endpoint(model_pin: dict[str, Any] | None) -> tuple[str, str]:
    source = _dict_at(model_pin, "source")
    endpoint = _dict_at(source, "endpoint")
    model = str((model_pin or {}).get("id") or "").strip()
    served = str(endpoint.get("servedName") or "").strip()
    base_url = str(endpoint.get("baseUrl") or "").strip().rstrip("/")
    if source.get("kind") != "endpoint" or not base_url or not model or served != model:
        raise VisionReviewError(
            "native vision review requires one exact endpoint model pin"
        )
    return base_url, model


def _post_json(url: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = (os.environ.get("WATCHSKILL_CUSTOM_API_KEY") or "lm-studio").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        raise VisionReviewError(
            f"vision endpoint HTTP {error.code}: {detail or error.reason}"
        ) from error
    if not isinstance(result, dict):
        raise VisionReviewError("vision endpoint returned a non-object response")
    return result


_PROBE_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/wcAAgAB/epv2AAAAABJRU5ErkJggg=="
)


def _live_probe(base_url: str, model: str, effective: dict[str, Any]) -> dict[str, Any]:
    prompt = 'Inspect the image and return JSON only: {"vision":true}.'
    payload = {
        "model": model,
        "reasoning_effort": "none",
        "temperature": 0,
        "max_tokens": 32,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{_PROBE_PNG}"},
                    },
                ],
            }
        ],
    }
    started = time.monotonic()
    response = _post_json(
        f"{base_url}/chat/completions",
        payload,
        timeout=int(effective["timeoutSeconds"]),
    )
    served = str(response.get("model") or model)
    return {
        "success": bool(response.get("choices")),
        "servedModel": served,
        "supportsVision": bool(response.get("choices")),
        "effectiveContextTokens": int(effective["contextLimit"]),
        "maxOutputTokens": int(effective["maxOutputTokens"]),
        "maxImages": int(effective["maxImagesPerPass"]),
        "maxWidth": int(effective["imageLongSide"]),
        "maxHeight": int(effective["imageLongSide"]),
        "detailModes": ["low"],
        "requestHash": hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "responseHash": hashlib.sha256(
            json.dumps(response, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "probedAt": datetime.now(UTC).isoformat(),
        "latencyMs": round((time.monotonic() - started) * 1000),
    }


def _ffprobe_video(candidate: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate,nb_frames,duration:format=duration",
            "-of",
            "json",
            str(candidate),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise VisionReviewError(f"ffprobe failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _video_geometry(candidate: Path) -> tuple[Fraction, int, float]:
    data = _ffprobe_video(candidate)
    streams = data.get("streams") or []
    if not streams:
        raise VisionReviewError("candidate has no video stream")
    stream = streams[0]
    fps = Fraction(str(stream.get("avg_frame_rate") or "0/1"))
    duration = float(
        stream.get("duration") or (data.get("format") or {}).get("duration") or 0
    )
    declared_frames = str(stream.get("nb_frames") or "").strip()
    frames = _declared_or_estimated_frames(declared_frames, duration, fps)
    _require_positive_geometry(fps, frames, duration)
    return fps, frames, duration


def _declared_or_estimated_frames(
    declared_frames: str, duration: float, fps: Fraction
) -> int:
    if declared_frames.isdigit():
        return int(declared_frames)
    return math.ceil(duration * float(fps))


def _require_positive_geometry(fps: Fraction, frames: int, duration: float) -> None:
    if fps <= 0:
        raise VisionReviewError("candidate has no usable frame rate")
    if frames <= 0 or duration <= 0:
        raise VisionReviewError("candidate duration/frame count is invalid")


def _frame_windows(
    windows: list[dict[str, Any]], *, fps: Fraction, duration_frames: int
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, window in enumerate(windows, 1):
        start = max(
            0, min(duration_frames - 1, math.floor(float(window["start"]) * float(fps)))
        )
        end = max(
            start + 1,
            min(duration_frames, math.ceil(float(window["end"]) * float(fps))),
        )
        result.append(
            {
                "windowId": f"required-{index:03d}",
                "startFrame": start,
                "endFrameExclusive": end,
                "mandatory": True,
                "riskClasses": [str(window.get("reason") or "declared-risk")],
                "source": deepcopy(window),
            }
        )
    return result


def _extract_exact_frame(
    candidate: Path, frame: int, directory: Path, long_side: int
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"frame-{frame:09d}.png"
    if path.is_file() and path.stat().st_size:
        return path
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(candidate),
            "-vf",
            f"select=eq(n\\,{frame}),scale={long_side}:{long_side}:force_original_aspect_ratio=decrease",
            "-vsync",
            "0",
            "-frames:v",
            "1",
            "-y",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not path.is_file() or not path.stat().st_size:
        path.unlink(missing_ok=True)
        raise VisionReviewError(
            completed.stderr.strip() or f"frame {frame} did not decode"
        )
    return path


def _choice_text(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise VisionReviewError("vision response has no choices")
    content = (choices[0].get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise VisionReviewError("vision response has no textual JSON content")
    return content


def _native_findings(
    raw: Any, *, review_pass: dict[str, Any], frame_refs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise VisionReviewError("vision findings must be a list")
    frames = list(review_pass.get("sampleFrames") or [])
    default_range = {
        "startFrame": min(frames),
        "endFrameExclusive": max(frames) + 1,
    }
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(raw, 1):
        findings.append(
            _native_finding(item, review_pass, index, default_range, frame_refs)
        )
    return findings


def _native_finding(
    item: Any,
    review_pass: dict[str, Any],
    index: int,
    default_range: dict[str, int],
    frame_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    item = _require_finding_item(item)
    severity = str(item.get("severity") or "warning")
    requires_human = bool(item.get("requiresHuman"))
    seed = json.dumps([review_pass["passId"], index, item], sort_keys=True)
    return validate_vision_finding(
        {
            "schemaVersion": "1.0.0",
            "findingId": f"vision-{hashlib.sha256(seed.encode()).hexdigest()[:16]}",
            "category": str(item.get("category") or "other"),
            "severity": severity,
            "confidence": float(item.get("confidence", 0.5)),
            "programRange": _fallback(item.get("programRange"), default_range),
            "evidenceRefs": deepcopy(frame_refs),
            "criterionIds": list(item.get("criterionIds") or []),
            "obligationIds": list(review_pass.get("requiredWindowIds") or []),
            "observed": str(item.get("observed") or item["message"]),
            "expected": str(
                item.get("expected")
                or "candidate satisfies the declared review criteria"
            ),
            "whyItMatters": str(item.get("whyItMatters") or item["message"]),
            "alternativeExplanations": list(item.get("alternativeExplanations") or []),
            "message": str(item["message"]),
            "suggestedAction": str(
                item.get("suggestedAction") or "inspect the cited frames"
            ),
            "requiresHuman": requires_human,
            "status": _finding_status(requires_human, severity),
            "humanDisposition": None,
        }
    )


def _require_finding_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict) or not str(item.get("message") or "").strip():
        raise VisionReviewError("vision finding must be an object with a message")
    return item


def _fallback(value: Any, default: Any) -> Any:
    return value if value not in (None, "", []) else default


def _finding_status(requires_human: bool, severity: str) -> str:
    return {
        True: "needs-human",
        False: {"blocking": "corroborated"}.get(severity, "open"),
    }[requires_human]


def _native_review(review: _ReviewRequest, model_pin: dict[str, Any]) -> dict[str, Any]:
    base_url, model = _native_endpoint(model_pin)
    effective = review.effective
    resource_policy = {
        "operatorManagedLifecycle": bool(effective["operatorManagedLifecycle"]),
        "concurrency": int(effective["concurrency"]),
        "vramCeilingBytes": int(effective["vramCeilingBytes"]),
        "allowedCoResidency": ["cpu-transcription"],
    }
    snapshot = probe_vision_capabilities(
        model_pin=model_pin,
        probe=lambda url, served: _live_probe(url, served, effective),
        resource_policy=resource_policy,
        conservative_context_limit=int(effective["contextLimit"]),
    )
    fps, duration_frames, duration_seconds = _video_geometry(review.candidate)
    windows = _frame_windows(review.windows, fps=fps, duration_frames=duration_frames)
    coverage_plan = compile_review_coverage(
        duration_frames=duration_frames,
        sections=[
            {
                "sectionId": "program",
                "startFrame": 0,
                "endFrameExclusive": duration_frames,
            }
        ],
        required_windows=windows,
        max_frames_per_pass=int(effective["maxImagesPerPass"]),
    )
    if coverage_plan["coverageHoles"]:
        raise VisionReviewError("mandatory vision coverage could not be planned")
    contract_seed = {
        "candidate": hashlib.sha256(review.candidate.read_bytes()).hexdigest(),
        "candidateIdentity": review.contract_context.get("candidateIdentityHash"),
        "dependencies": review.contract_context.get("dependencies") or {},
        "policy": review.policy_payload.get("policyHash"),
        "coverage": coverage_plan,
        "capability": snapshot["identityHash"],
        "prompt": hashlib.sha256(review.prompt.encode("utf-8")).hexdigest(),
        "transcript": (
            hashlib.sha256(Path(review.transcript_ref).read_bytes()).hexdigest()
            if review.transcript_ref and Path(review.transcript_ref).is_file()
            else None
        ),
        "terms": review.terms,
        "names": review.names,
        "tool": "avo-native-vision/1.0.0",
    }
    contract_hash = hashlib.sha256(
        json.dumps(contract_seed, sort_keys=True).encode("utf-8")
    ).hexdigest()
    contract_dir = review.artifact_dir / contract_hash
    frames_dir = contract_dir / "frames"
    raw_dir = contract_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    def invoke(_candidate_index: str, review_pass: dict[str, Any]) -> dict[str, Any]:
        requested = [int(frame) for frame in review_pass.get("sampleFrames") or []]
        decoded: list[int] = []
        failed: list[int] = []
        paths: list[Path] = []
        for frame in requested:
            try:
                paths.append(
                    _extract_exact_frame(
                        review.candidate,
                        frame,
                        frames_dir,
                        int(effective["imageLongSide"]),
                    )
                )
                decoded.append(frame)
            except VisionReviewError:
                failed.append(frame)
        if failed:
            return {
                "status": "blocked",
                "model": model,
                "requestedFrames": requested,
                "decodedFrames": decoded,
                "failedFrames": failed,
                "observedFrames": [],
                "findings": [],
            }
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": review.prompt
                + "\nThis pass is "
                + str(review_pass["passId"])
                + ". Finding fields allowed: category, severity, confidence, message, requiresHuman, observed, expected, whyItMatters, suggestedAction. category must be one of layout, pacing, movement, continuity, privacy, caption, visual-quality, editorial, factual-risk, rights, accessibility, technical, other. severity must be one of info, warning, blocking, unknown.",
            }
        ]
        refs: list[dict[str, Any]] = []
        for frame, path in zip(decoded, paths, strict=True):
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            refs.append(
                {
                    "kind": "decoded-frame",
                    "artifactId": f"frame-{frame}",
                    "sha256": digest,
                    "path": str(path),
                }
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,"
                        + base64.b64encode(data).decode("ascii"),
                        "detail": "low",
                    },
                }
            )
        payload = {
            "model": model,
            "reasoning_effort": "none",
            "temperature": 0,
            "max_tokens": int(effective["maxOutputTokens"]),
            "messages": [{"role": "user", "content": content}],
        }
        response = _post_json(
            f"{base_url}/chat/completions",
            payload,
            timeout=int(effective["timeoutSeconds"]),
        )
        raw_path = raw_dir / f"{review_pass['passId']}.json"
        raw_path.write_text(
            json.dumps(response, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        analysis = _extract_json_object(_choice_text(response))
        status = str(analysis.get("status") or "")
        if status not in _VALID_WATCH_STATUS:
            raise VisionReviewError("vision response has an invalid status")
        response_model = str(response.get("model") or "")
        return {
            "status": status,
            "model": response_model,
            "capabilityIdentityHash": snapshot["identityHash"],
            "lifecycleActions": [],
            "requestedFrames": requested,
            "decodedFrames": decoded,
            "failedFrames": [],
            "observedFrames": decoded,
            "findings": _native_findings(
                analysis.get("findings"), review_pass=review_pass, frame_refs=refs
            ),
            "rawArtifactRefs": [_raw_artifact_ref(raw_path, kind="endpoint-response")],
        }

    execution = execute_bounded_passes(
        candidate_index=hashlib.sha256(review.candidate.read_bytes()).hexdigest(),
        passes=[
            {
                **item,
                "requiredFrames": item["sampleFrames"],
                "maxAttempts": int(effective["analysisAttempts"]),
            }
            for item in coverage_plan["passes"]
        ],
        capability_snapshot=snapshot,
        invoke=invoke,
    )
    required_ids = [item["passId"] for item in coverage_plan["passes"]]
    statuses = {item["status"] for item in execution["passResults"]}
    aggregate_status = (
        "blocked"
        if "blocked" in statuses
        else "fail"
        if "fail" in statuses
        else "needs-human-judgment"
        if "needs-human-judgment" in statuses
        else "pass"
    )
    observed = set(execution["observedSamples"])
    observed_windows = []
    for window in windows:
        pass_frames = {
            frame
            for item in coverage_plan["passes"]
            if window["windowId"] in item.get("requiredWindowIds", [])
            for frame in item["sampleFrames"]
        }
        if pass_frames and pass_frames.issubset(observed):
            observed_windows.append(window["source"])
    holes = list(coverage_plan["coverageHoles"])
    if len(observed_windows) != len(windows):
        holes.append({"reason": "required-window-not-observed", "mandatory": True})
        aggregate_status = "blocked"
    coverage_manifest_path = contract_dir / "coverage-manifest.json"
    coverage_manifest_payload = {
        "reviewContractHash": contract_hash,
        "planHash": hashlib.sha256(
            json.dumps(coverage_plan, sort_keys=True).encode()
        ).hexdigest(),
        "requiredPassIds": required_ids,
        "requestedFrames": execution["requestedSamples"],
        "decodedFrames": execution["decodedSamples"],
        "failedFrames": execution["failedSamples"],
        "observedFrames": execution["observedSamples"],
        "observedWindows": observed_windows,
        "coverageHoles": holes,
        "aggregateStatus": aggregate_status,
    }
    coverage_manifest_path.write_text(
        json.dumps(
            coverage_manifest_payload, indent=2, ensure_ascii=False, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    coverage_ref = _raw_artifact_ref(
        coverage_manifest_path, kind="vision-coverage-manifest"
    )
    coverage_artifact = {key: coverage_ref[key] for key in ("path", "sha256", "kind")}
    evidence = {
        "schemaVersion": "1.0.0",
        "status": aggregate_status,
        "checkpoint": review.checkpoint,
        "candidate": str(review.candidate),
        "coverage": {
            "mode": "full",
            "sampling": "native-frames",
            "samplingMode": coverage_plan["samplingMode"],
            "durationSeconds": duration_seconds,
            "frameRate": {"num": fps.numerator, "den": fps.denominator},
            "requestedWindows": review.windows,
            "observedWindows": observed_windows,
            "windows": observed_windows,
            "requestedFrames": execution["requestedSamples"],
            "decodedFrames": execution["decodedSamples"],
            "failedFrames": execution["failedSamples"],
            "observedFrames": execution["observedSamples"],
            "inspectedRanges": [
                {"startFrame": frame, "endFrameExclusive": frame + 1}
                for frame in execution["observedSamples"]
            ],
            "coverageHoles": holes,
        },
        "findings": [
            finding for item in execution["passResults"] for finding in item["findings"]
        ],
        "tool": "avo-native-vision",
        "toolVersion": "1.0.0",
        "model": model,
        "policy": review.policy_payload,
        "reviewContext": review.context,
        "promptSha256": hashlib.sha256(review.prompt.encode("utf-8")).hexdigest(),
        "capabilitySnapshot": snapshot,
        "capabilityIdentityHash": snapshot["identityHash"],
        "coveragePlan": coverage_plan,
        "coveragePlanHash": hashlib.sha256(
            json.dumps(coverage_plan, sort_keys=True).encode()
        ).hexdigest(),
        "reviewContractHash": contract_hash,
        "requiredPassIds": required_ids,
        "passResults": execution["passResults"],
        "rawArtifactRefs": [
            ref for item in execution["passResults"] for ref in item["rawArtifactRefs"]
        ],
        "automationComplete": aggregate_status != "blocked" and not holes,
        "visionCoverageManifest": {
            "planHash": coverage_manifest_payload["planHash"],
            "reviewContractHash": contract_hash,
            "aggregateStatus": aggregate_status,
            "artifact": coverage_artifact,
        },
        "disposition": (
            "blocked"
            if aggregate_status == "blocked"
            else "fail"
            if aggregate_status in {"fail", "needs-human-judgment"}
            else "pass"
        ),
        "outcomeKind": "uncertainty"
        if aggregate_status == "needs-human-judgment"
        else "content",
    }
    evidence_path = contract_dir / "watch-evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        **evidence,
        "artifacts": [
            str(evidence_path),
            str(coverage_manifest_path),
            *[ref["path"] for ref in evidence["rawArtifactRefs"]],
        ],
    }


def _take_source_preflight(source: Path, raw_dir: Path, expected_sha256: str) -> None:
    relative = source.resolve().relative_to(raw_dir.resolve())
    if relative.parts[0].casefold() == "edit":
        raise ValueError("take vision requires an original outside edit outputs")
    if file_fingerprint(source)["sha256"] != expected_sha256:
        raise ValueError("original take source fingerprint changed")


def _take_windows(takes: list[dict]) -> list[dict]:
    windows = []
    source_ids = set()
    for take in takes:
        identity = take.get("takeId") or take.get("unitId")
        if not identity:
            raise ValueError("original visual take requires a stable identity")
        source_id, start, end = source_interval(take["sourceRange"])
        source_ids.add(source_id)
        windows.append(
            {
                "start": float(start),
                "end": float(end),
                "reason": f"takeId={identity}: visual usability",
                "takeId": identity,
            }
        )
    if len(source_ids) != 1:
        raise ValueError("original take windows must use one source")
    return windows


def _take_observed_frames(take: dict, review: dict) -> list[int]:
    coverage = review.get("coverage") or {}
    rate = coverage.get("frameRate") or {}
    _, start, end = source_interval(take["sourceRange"])
    fps = Fraction(rate.get("num", 0), rate.get("den", 1))
    observed = (
        [
            frame
            for frame in coverage.get("observedFrames", [])
            if start <= Fraction(frame, 1) / fps < end
        ]
        if fps
        else []
    )
    return observed


def _take_visual_findings(identity: str, review: dict) -> list[dict]:
    prefix = f"takeId={identity}; usability="
    findings = [
        finding
        for finding in review.get("findings", [])
        if finding.get("category") == "visual-quality"
        and str(finding.get("observed", "")).startswith(prefix)
    ]
    return findings


def _take_visual_eligible(review: dict, observed: list) -> bool:
    coverage = review.get("coverage") or {}
    eligible = all(
        (
            review.get("status") == "pass",
            not coverage.get("coverageHoles"),
            bool(observed),
            bool(review.get("model")),
            bool(review.get("promptSha256")),
            bool(review.get("capabilityIdentityHash")),
            bool(review.get("reviewContractHash")),
        )
    )
    return eligible


def _take_visual_observation(take: dict, review: dict) -> dict:
    identity = str(take.get("takeId") or take.get("unitId"))
    prefix = f"takeId={identity}; usability="
    observed = _take_observed_frames(take, review)
    findings = _take_visual_findings(identity, review)
    labels = {str(finding["observed"])[len(prefix) :].strip() for finding in findings}
    usability = None
    if _take_visual_eligible(review, observed) and len(labels) == 1:
        usability = {"usable": 1.0, "unusable": 0.0}.get(next(iter(labels)))
    return {
        "visualUsability": usability,
        "observations": deepcopy(findings),
        "observedFrames": observed,
        "claimScope": "sampled-still-images",
    }


def _take_semantic_response(review: dict):
    prefix = "take-semantics-json="
    responses = [
        str(item.get("observed", ""))[len(prefix) :]
        for item in review.get("findings", [])
        if str(item.get("observed", "")).startswith(prefix)
    ]
    if len(responses) != 1:
        return None
    try:
        return json.loads(responses[0])
    except (ValueError, TypeError):
        return None


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
        models_used: dict[str, str] = {}
        model_sources: dict[str, Any] = {}
        try:
            from avo.model_sources import (
                disclosure_for,
                invocation_from_env,
                resolve_job,
            )

            resolved = resolve_job(
                "understand",
                root=request.root,
                invocation=invocation_from_env(environment),
            )
            if resolved.id:
                models_used = {"understand": resolved.catalog_label or resolved.id}
                model_sources = {"understand": disclosure_for(resolved)}
        except Exception:
            pass
        return JobResult(
            exit_code=completed.returncode,
            artifact_paths=artifacts,
            stdout=stdout,
            stderr=completed.stderr or "",
            models_used=models_used,
            model_sources=model_sources,
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

    def review_original_takes(
        self,
        source: Path,
        *,
        source_sha256: str,
        takes: list[dict],
        raw_dir: Path,
        **request: Any,
    ) -> dict:
        """Reuse configured Watch for visual observations of fingerprinted takes."""
        source, raw_dir = Path(source), Path(raw_dir)
        _take_source_preflight(source, raw_dir, source_sha256)
        policy_payload, effective = _policy_settings(request)
        if effective["concurrency"] != 1 or effective["vramCeilingBytes"] > 7 * 1024**3:
            raise ValueError(
                "original take visual resource policy must remain serialized and within 7 GB"
            )
        windows = _take_windows(takes)
        context = deepcopy(request.get("context") or {})
        context.setdefault("acceptanceCriteria", []).append(
            "For each declared takeId, provide a visual-quality finding observed exactly 'takeId=<id>; usability=usable', 'takeId=<id>; usability=unusable', or 'takeId=<id>; usability=unknown'. Assess only visible focus/framing/obstruction at sampled frames. Do not certify audio, complete speech or continuous movement."
        )
        review_request = {
            **request,
            "scope": "windows",
            "windows": windows,
            "context": context,
        }
        review = self.review(source, **review_request)
        _take_source_preflight(source, raw_dir, source_sha256)
        return {
            "sourceSha256": source_sha256,
            "sourceRanges": [deepcopy(take["sourceRange"]) for take in takes],
            "modelIdentity": review.get("model"),
            "capabilityIdentityHash": review.get("capabilityIdentityHash"),
            "promptHash": review.get("promptSha256"),
            "reviewContractHash": review.get("reviewContractHash"),
            "inputHash": content_hash(
                {
                    "sourceSha256": source_sha256,
                    "takes": takes,
                    "policy": policy_payload,
                    "promptHash": review.get("promptSha256"),
                    "modelIdentity": review.get("model"),
                }
            ),
            "claimScope": "sampled-still-images",
            "semanticResponse": _take_semantic_response(review),
            "status": "inferred" if review.get("status") == "pass" else "blocked",
            "perTake": {
                str(take.get("takeId") or take.get("unitId")): _take_visual_observation(
                    take, review
                )
                for take in takes
            },
        }

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
        option_id = _option_id(request.get("option_id"))
        pin = request.get("model_pin")
        if not isinstance(pin, dict):
            pin = None
            try:
                from avo.model_sources import invocation_from_env, resolve_job

                resolved = resolve_job(
                    "understand",
                    root=_repository_root(),
                    invocation=invocation_from_env(os.environ),
                )
                if resolved.id == option_id:
                    pin = resolved.pin
            except Exception:
                pin = None
        _require_bonsai_runtime(option_id, pin=pin)
        review = _review_request(candidate, request)
        if pin and _dict_at(pin, "source").get("kind") == "endpoint":
            try:
                return _native_review(review, pin)
            except Exception as error:
                if isinstance(error, ToolError):
                    raise
                raise ToolError(
                    "WATCH_NATIVE_BLOCKED",
                    f"native structured vision review blocked: {error}",
                    True,
                    "keep the pinned model loaded, verify the endpoint, and rerun the exact candidate",
                ) from error
        watched, video_id = _acquire_candidate(self, review)
        analysis_run = _analyze_candidate(self, review, video_id)
        report_path, analysis_path, raw_paths = _write_raw_artifacts(
            review, watched, analysis_run.attempts
        )
        payload = _evidence_payload(
            self, review, analysis_run, report_path, analysis_path, raw_paths
        )
        evidence_path = _write_evidence(review, payload)
        return {
            **payload,
            "artifacts": [
                str(report_path),
                str(analysis_path),
                *[str(path) for path in raw_paths],
                str(evidence_path),
                *[
                    str(path)
                    for path in watched.artifact_paths
                    + analysis_run.result.artifact_paths
                ],
            ],
        }
