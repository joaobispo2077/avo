"""Remotion motion job stub."""

from __future__ import annotations

from helpers.adapters.base import JobRequest, JobResult


class RemotionStubAdapter:
    routing_id = "remotion"

    def run(self, request: JobRequest) -> JobResult:
        doc = request.root / "docs" / "remotion-decision-guide.md"
        if not doc.is_file():
            return JobResult(exit_code=2, stderr=f"missing {doc}")
        return JobResult(
            exit_code=2,
            stderr="remotion stub: per-project install documented in remotion-decision-guide.md",
        )
