# Installed Watch Skill boundary with structured AVO review evidence.

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from avo.adapters.base import JobRequest, JobResult
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


def _extract_json_object(text: str) -> dict[str, Any]:
    candidates = re.findall(
        r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE
    )
    candidates.extend(text[index:] for index, char in enumerate(text) if char == "{")
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value, _ = decoder.raw_decode(candidate.strip())
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("Watch analysis did not return a JSON object")


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
        try:
            completed = subprocess.run(
                [self.executable, *request.argv],
                cwd=request.root,
                env={**os.environ, **request.env},
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            return JobResult(exit_code=2, stderr=f"watch-skill unavailable: {error}")
        artifacts = [
            Path(line.strip())
            for line in completed.stdout.splitlines()
            if line.strip().endswith((".json", ".md", ".html"))
            and Path(line.strip()).exists()
        ]
        return JobResult(
            exit_code=completed.returncode,
            artifact_paths=artifacts,
            stdout=completed.stdout,
            stderr=completed.stderr,
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
        scope = str(request.get("scope") or "full")
        windows = list(request.get("windows") or [])
        self.validate_coverage(scope, windows)
        # Resolve understand against the AVO repo catalog — never the candidate/tmp root.
        option_id = request.get("option_id")
        if option_id is None:
            try:
                from avo.models import resolve_option_id

                option_id = resolve_option_id("understand", root=_repository_root())
            except Exception:
                option_id = ""
        _require_bonsai_runtime(str(option_id or ""))
        artifact_dir = Path(
            request.get("artifact_dir")
            or Path(request.get("root") or candidate.parent) / ".avo-watch"
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = str(request.get("checkpoint") or "cut-proof")
        question = (
            f"Collect evidence for the exact {checkpoint} candidate: visual continuity, "
            "lip sync, cut edges, face/overlay conflicts, text readability, privacy, and meaning."
        )
        argv = [
            "watch",
            str(candidate),
            question,
            "--out-dir",
            str(artifact_dir),
            "--index",
        ]
        timestamps: list[float] = []
        for window in windows:
            timestamps.extend(
                [
                    float(window["start"]),
                    (float(window["start"]) + float(window["end"])) / 2,
                    float(window["end"]),
                ]
            )
        if timestamps:
            argv.extend(
                [
                    "--timestamps",
                    ",".join(f"{value:.3f}" for value in sorted(set(timestamps))),
                ]
            )
        root = Path(request.get("root") or candidate.parent)
        watched = self.run(
            JobRequest(
                job="understand", label=f"Watch {candidate.name}", argv=argv, root=root
            )
        )
        if watched.exit_code != 0:
            raise self._tool_error(watched, "acquisition")
        match = re.search(r"video_id\s+`([^`]+)`", watched.stdout)
        if not match:
            raise ToolError(
                "WATCH_MALFORMED",
                "Watch acquisition did not return an indexed video id",
                True,
                "retry Watch on the exact candidate; if repeated, run watch-skill doctor",
            )
        video_id = match.group(1)
        analysis_contract = {
            "status": "pass|fail|needs-human-judgment",
            "confidence": "number 0..1",
            "findings": [
                {
                    "classification": "technical|meaning|rights|privacy|policy|safety",
                    "severity": "info|warning|blocker",
                    "message": "specific observation",
                    "start": "seconds or null",
                    "end": "seconds or null",
                }
            ],
        }
        prompt = (
            f"Review video evidence for checkpoint {checkpoint}. Required scope={scope}; "
            f"required windows={json.dumps(windows, ensure_ascii=False)}. "
            "Return ONLY one JSON object matching this contract: "
            f"{json.dumps(analysis_contract, ensure_ascii=False)}. "
            "Use pass only when no blocker exists. Never invent unseen evidence; use "
            "needs-human-judgment for meaning, rights, privacy, policy, or safety ambiguity."
        )
        analyzed = self.run(
            JobRequest(
                job="understand",
                label=f"Analyze {candidate.name}",
                argv=["ask", video_id, prompt, "--frames", "--no-cache"],
                root=root,
            )
        )
        if analyzed.exit_code != 0:
            raise self._tool_error(analyzed, "analysis")
        try:
            analysis = _extract_json_object(analyzed.stdout)
        except ValueError as error:
            raise ToolError(
                "WATCH_MALFORMED",
                str(error),
                True,
                "retry the exact candidate; repeated malformed output blocks the gate",
            ) from error
        status = str(analysis.get("status") or "")
        if status not in {"pass", "fail", "needs-human-judgment"}:
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
        report_path = artifact_dir / "watch-report.md"
        report_path.write_text(watched.stdout, encoding="utf-8")
        analysis_path = artifact_dir / "watch-analysis.txt"
        analysis_path.write_text(analyzed.stdout, encoding="utf-8")
        payload = {
            "schemaVersion": "1.0.0",
            "status": status,
            "checkpoint": checkpoint,
            "candidate": str(candidate),
            "coverage": {
                "mode": "full" if scope in {"full", "whole"} else "windows",
                "windows": windows,
            },
            "findings": findings,
            "confidence": analysis.get("confidence"),
            "tool": "watch-skill",
            "toolVersion": self.tool_version(),
            "model": analysis.get("model"),
            "rawReport": str(report_path),
            "rawAnalysis": str(analysis_path),
        }
        evidence_path = artifact_dir / "watch-evidence.json"
        evidence_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            **payload,
            "artifacts": [
                str(report_path),
                str(analysis_path),
                str(evidence_path),
                *[
                    str(path)
                    for path in watched.artifact_paths + analyzed.artifact_paths
                ],
            ],
        }
