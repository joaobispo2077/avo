"""speckit plan job stub."""

from __future__ import annotations

from avo.adapters.base import JobRequest, JobResult


class SpeckitStubAdapter:
    routing_id = "speckit"

    def run(self, request: JobRequest) -> JobResult:
        marker = request.root / ".specify"
        if not marker.exists():
            return JobResult(
                exit_code=2,
                stderr="speckit stub: .specify marker missing — install GitHub Spec Kit",
            )
        return JobResult(
            exit_code=2,
            stderr="speckit stub: marker present. Use /speckit.* commands via agent boundary.",
        )
