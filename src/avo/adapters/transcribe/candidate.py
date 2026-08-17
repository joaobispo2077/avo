"""Exact-candidate transcription and transcript-risk analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from avo.timeline.contracts import file_fingerprint
from avo.timeline.ports import ToolError


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

    def transcribe(self, candidate: Path, **options: Any) -> dict[str, Any]:
        candidate = Path(candidate)
        fingerprint = file_fingerprint(candidate)
        try:
            if self.runtime is not None:
                if hasattr(self.runtime, "transcribe"):
                    payload = self.runtime.transcribe(candidate, **options)
                else:
                    payload = self.runtime(candidate, **options)
                transcript_path = options.get("transcript_path")
            else:
                from avo.transcribe import transcribe_one

                edit_dir = Path(options["edit_dir"])
                path = transcribe_one(
                    candidate, edit_dir, model=self.model, verbose=False
                )
                payload = json.loads(path.read_text(encoding="utf-8"))
                transcript_path = path
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
            or "pt-BR",
            "words": payload.get("words") or [],
            "findings": findings,
        }
