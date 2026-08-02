"""HyperFrames motion job stub."""

from __future__ import annotations

import json

from avo.adapters.base import JobRequest, JobResult


class HyperframesStubAdapter:
    routing_id = "hyperframes"

    def run(self, request: JobRequest) -> JobResult:
        pkg_json = request.root / "package.json"
        if not pkg_json.is_file():
            return JobResult(exit_code=2, stderr="package.json missing")
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        if "hyperframes" not in deps:
            return JobResult(exit_code=2, stderr="hyperframes not declared in package.json")
        return JobResult(
            exit_code=2,
            stderr="hyperframes stub: package declared. Use npx hyperframes via subprocess boundary.",
        )
