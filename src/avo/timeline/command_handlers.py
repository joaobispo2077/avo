"""Shared runtime handlers; Markdown command files provide intent only."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .command_registry import authorize, command_spec
from .pipeline import TimelinePipeline


class CommandHandlers:
    def __init__(
        self,
        pipeline: TimelinePipeline,
        *,
        evidence_runner: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.evidence_runner = evidence_runner

    def execute(
        self,
        command: str,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(payload or {})
        spec = command_spec(command)
        mutation = payload.pop("mutation", None)
        target_scope = str(payload.pop("targetScope", "current"))
        parent_ref = payload.pop("parentTimelineRef", None)
        authorize(
            command,
            mutation=mutation,
            writes_evidence=operation == "evidence",
            target_scope=target_scope,
            parent_timeline_ref=parent_ref,
        )

        if spec.mode in {"Admin", "Consumes"}:
            if operation not in {"status", "inspect", "validate", "deliver"}:
                raise ValueError(
                    f"{command} is read-only; unsupported operation {operation}"
                )
            return {
                "command": command,
                "mode": spec.mode,
                "operation": operation,
                "mutated": False,
                "timeline": self.pipeline.status(),
            }
        if spec.mode == "Evidence":
            if operation != "evidence" or self.evidence_runner is None:
                raise ValueError(f"{command} requires the shared evidence runner")
            result = self.evidence_runner(command=command, **payload)
            return {
                "command": command,
                "mode": spec.mode,
                "mutated": False,
                "evidence": result,
            }
        if spec.mode == "Profile":
            child_project = Path(str(payload.get("childProject") or ""))
            if not child_project.is_file():
                raise ValueError(
                    "profile command requires an initialized child project"
                )
            if (
                child_project.resolve()
                == self.pipeline.workspace.project_path.resolve()
            ):
                raise ValueError("profile command cannot mutate parent timeline")
            return {
                "command": command,
                "mode": spec.mode,
                "mutated": False,
                "childProject": str(child_project),
                "parentTimelineRef": parent_ref,
            }

        if command in {"sound", "media", "captions", "color", "grade", "end-screen"}:
            result = self.pipeline.apply_assembly_stage(owner=command, **payload)
        elif command == "pipeline":
            result = self.pipeline.advance(operation, **payload)
        else:
            result = {
                "operation": operation,
                "artifact": mutation,
                "guarded": True,
                "timeline": self.pipeline.status(),
            }
        return {
            "command": command,
            "mode": spec.mode,
            "mutated": True,
            "result": result,
        }
