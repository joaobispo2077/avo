"""ai-memory job stub."""

from __future__ import annotations

from helpers.adapters.base import JobRequest, JobResult


class AiMemoryStubAdapter:
    routing_id = "ai-memory"

    def run(self, request: JobRequest) -> JobResult:
        path = request.root / "tools" / "ai-memory"
        if path.is_dir() and any(path.iterdir()):
            note = f"present at {path}"
        else:
            note = "optional — not cloned (run setup --with-memory)"
        return JobResult(
            exit_code=2,
            stderr=f"ai-memory stub: {note}. Invoke via MCP/subprocess boundary only.",
        )
