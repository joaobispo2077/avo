"""Exact-candidate transcription and transcript-risk analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from avo.timeline.contracts import file_fingerprint
from avo.timeline.ports import ToolError


def _matching_transcript(
    path: Path, sha256: str, *, model: str | None = None
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("words"), list):
        return None
    source = (payload.get("source") or {}).get("sha256") or payload.get("sourceSha256")
    if source != sha256:
        return None
    if model is not None and payload.get("model") != model:
        return None
    return payload


class CandidateTranscriptionAdapter:
    def __init__(self, runtime: Any | None = None, *, model: str = "small"):
        self.runtime = runtime
        self.model = model

    @staticmethod
    def analyze(
        payload: dict[str, Any],
        *,
        risk_windows: list[dict[str, Any]] | None = None,
        terms: list[str] | None = None,
        names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        findings = []
        words = payload.get("words") or []
        text = str(payload.get("text") or "")
        for expected in [*(terms or []), *(names or [])]:
            if expected.casefold() not in text.casefold():
                findings.append(
                    {
                        "id": f"missing-term-{expected}",
                        "classification": "factual",
                        "message": f"expected name/term not found: {expected}",
                    }
                )
        for window in risk_windows or []:
            start = float(window.get("start", 0))
            end = float(window.get("end", start))
            near = [
                word
                for word in words
                if float(word.get("start", 0)) <= end
                and float(word.get("end", 0)) >= start
            ]
            if not near:
                findings.append(
                    {
                        "id": f"transcript-gap-{start:.3f}",
                        "classification": "cut-edge",
                        "message": "no transcript words cover a required cut/risk window",
                    }
                )
            for word in near:
                if float(word.get("probability", 1.0)) < 0.4:
                    findings.append(
                        {
                            "id": f"low-confidence-{word.get('start')}",
                            "classification": "factual",
                            "message": "low-confidence word at cut/risk window",
                        }
                    )
        return findings

    def _load_transcript_payload(
        self, candidate: Path, fingerprint: dict[str, Any], options: dict[str, Any]
    ) -> tuple[dict[str, Any], Any]:
        if self.runtime is not None:
            payload = (
                self.runtime.transcribe(candidate, **options)
                if hasattr(self.runtime, "transcribe")
                else self.runtime(candidate, **options)
            )
            return payload, options.get("transcript_path")
        from avo.transcribe import transcribe_one
        from avo.transcribe import transcript_path as out_path

        edit_dir = Path(options["edit_dir"])
        path = out_path(candidate, edit_dir)
        payload = _matching_transcript(path, fingerprint["sha256"], model=self.model)
        if payload is None:
            path = transcribe_one(
                candidate,
                edit_dir,
                model=self.model,
                device=str(options.get("device") or "auto"),
                verbose=False,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
        return payload, path

    def transcribe(self, candidate: Path, **options: Any) -> dict[str, Any]:
        candidate = Path(candidate)
        fingerprint = file_fingerprint(candidate)
        try:
            payload, transcript_path = self._load_transcript_payload(
                candidate, fingerprint, options
            )
        except Exception as exc:
            raise ToolError(
                "TRANSCRIPTION_UNAVAILABLE",
                str(exc),
                True,
                "prepare the local multilingual model and retry",
            ) from exc
        source = (payload.get("source") or {}).get("sha256") or payload.get(
            "sourceSha256"
        )
        if source != fingerprint["sha256"]:
            raise ToolError(
                "TRANSCRIPT_STALE",
                "transcript source hash does not match candidate",
                False,
                "transcribe the exact current candidate",
            )
        findings = self.analyze(
            payload,
            risk_windows=options.get("risk_windows"),
            terms=options.get("terms"),
            names=options.get("names"),
        )
        return {
            "status": "pass" if not findings else "fail",
            "sourceSha256": source,
            "transcriptPath": str(transcript_path or ""),
            "engine": payload.get("engine") or "test",
            "engineVersion": payload.get("engine_version")
            or payload.get("engineVersion")
            or "unknown",
            "model": payload.get("model") or self.model,
            "language": payload.get("language_code")
            or payload.get("language")
            or "unknown",
            "words": payload.get("words") or [],
            "findings": findings,
        }
