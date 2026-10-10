"""Shared runtime handlers; Markdown command files provide intent only."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from .command_registry import authorize, command_spec
from .pipeline import TimelinePipeline


def _prepare_command(command, operation, payload):
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
    return payload, spec, mutation, parent_ref


def _execute_cutting(service, operation, payload, spec):
    if operation not in {"analyze", "preview", "decide", "apply", "status"}:
        raise ValueError(f"unsupported trim operation: {operation}")
    if service is None:
        raise ValueError("trim requires an injected CuttingService")
    if operation == "analyze":
        result = service.analyze(payload.pop("request", None))
    elif operation == "decide":
        result = service.decide(payload.pop("proposalRef"), payload.pop("request"))
    elif operation == "status":
        result = service.status(payload.pop("proposalRef", None))
    else:
        result = getattr(service, operation)(payload.pop("proposalRef"))
    return {
        "command": "trim",
        "mode": spec.mode,
        "operation": operation,
        "mutated": operation == "apply" and result.get("status") == "applied",
        "result": result,
    }


class CommandHandlers:
    def __init__(
        self,
        pipeline: TimelinePipeline,
        *,
        evidence_runner: Callable[..., dict[str, Any]] | None = None,
        cutting_service: Any | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.evidence_runner = evidence_runner
        self.cutting_service = cutting_service

    def _rework_status(self) -> dict[str, Any]:
        """Project current classifications while retaining every prior attribution."""
        from .review_study import build_rework_report

        timeline_dir = getattr(self.pipeline.workspace, "timeline_dir", None)
        ledger_path = (
            Path(timeline_dir) / "iteration-ledger.json" if timeline_dir else None
        )
        if ledger_path is None or not ledger_path.is_file():
            ledger = {"ledgerHash": None, "reworkItems": []}
        else:
            from .iterations import IterationLedgerService

            ledger = IterationLedgerService(self.pipeline.workspace).current()

        items = list(ledger.get("reworkItems") or [])
        replacement_by_id = {
            str(item["supersedes"]): str(item["reworkId"])
            for item in items
            if item.get("supersedes")
        }
        history = []
        for item in items:
            value = deepcopy(item)
            replacement = replacement_by_id.get(str(item.get("reworkId")))
            value["status"] = "superseded" if replacement else "active"
            value["supersededBy"] = replacement
            history.append(value)
        return {
            "ledgerHash": ledger.get("ledgerHash"),
            **build_rework_report(ledger),
            "classificationHistory": history,
        }

    def execute(
        self,
        command: str,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload, spec, mutation, parent_ref = _prepare_command(
            command, operation, payload
        )

        if command == "trim":
            return _execute_cutting(self.cutting_service, operation, payload, spec)

        if command == "thumbnail" and operation == "extract":
            from .stills import StillExtractionService

            result = StillExtractionService(self.pipeline.workspace).extract(**payload)
            return {
                "command": command,
                "mode": spec.mode,
                "operation": operation,
                "mutated": False,
                "result": result,
            }

        if command == "pipeline" and operation == "proof-status":
            proof_plan = payload.pop("proofPlan", None)
            if proof_plan is None:
                return {
                    "command": command,
                    "mode": spec.mode,
                    "operation": operation,
                    "mutated": False,
                    "candidate": self.pipeline.candidate_status(),
                    "rework": self._rework_status(),
                }
            result = self.pipeline.proof_build_status(
                proof_plan=proof_plan,
                media_inputs=payload.pop("mediaInputs", {}),
                microproof_gate=payload.pop("microproofGate", None),
                render_port=payload.pop("renderPort", None),
            )
            result["rework"] = self._rework_status()
            return {
                "command": command,
                "mode": spec.mode,
                "operation": operation,
                "mutated": False,
                "result": result,
            }

        if command == "pipeline" and operation == "proof-microproof":
            result = self.pipeline.render_proof_microproofs(
                proof_plan=payload.pop("proofPlan"),
                media_inputs=payload.pop("mediaInputs"),
                render_port=payload.pop("renderPort", None),
            )
            return {
                "command": command,
                "mode": spec.mode,
                "operation": operation,
                "mutated": True,
                "result": result,
            }

        if command == "pipeline" and operation == "proof-build":
            result = self.pipeline.build_proof_candidate(
                proof_plan=payload.pop("proofPlan"),
                microproof_gate=payload.pop("microproofGate"),
                media_inputs=payload.pop("mediaInputs"),
                expected_active_snapshot_hash=payload.pop(
                    "expectedActiveSnapshotHash", None
                ),
                render_port=payload.pop("renderPort", None),
            )
            return {
                "command": command,
                "mode": spec.mode,
                "operation": operation,
                "mutated": True,
                "result": result,
            }

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
            response = {
                "command": command,
                "mode": spec.mode,
                "mutated": False,
                "evidence": result,
            }
            if command == "watch" and isinstance(result.get("reviewPackage"), dict):
                from .review import render_human_review_package

                response["reviewPackageMarkdown"] = render_human_review_package(
                    result["reviewPackage"]
                )
            return response
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

        if command == "pipeline" and operation == "record-iteration":
            from .iterations import IterationLedgerService

            iteration = payload.pop("iteration", None)
            if not isinstance(iteration, dict):
                raise ValueError("record-iteration requires an iteration object")
            actor = payload.pop("actor", None)
            reason = payload.pop("reason", None)
            if not actor or not reason:
                raise ValueError("record-iteration requires actor and reason")
            result = IterationLedgerService(self.pipeline.workspace).record_iteration(
                iteration,
                actor=actor,
                reason=str(reason),
                expected_head_hash=payload.pop("expectedHeadHash", None),
            )
            result = {
                "operation": operation,
                "artifact": "iteration-ledger",
                "iterationId": result["iteration"]["iterationId"],
                "ledgerHash": result["ledger"]["ledgerHash"],
                "revision": result["revision"],
            }
        elif command == "pipeline" and operation == "component-scaffold":
            from .component_instances import ComponentInstanceService

            gap = payload.pop("capabilityGap", None) or {}
            if gap.get("status") != "unsupported":
                raise ValueError(
                    "component-scaffold requires an unsupported capability gap"
                )
            component_id = str(payload.pop("componentId"))
            result = ComponentInstanceService(self.pipeline.workspace).scaffold(
                component_id
            )
        elif command == "pipeline" and operation == "component-register":
            from .component_instances import ComponentInstanceService
            from .generated_assets import GeneratedAssetService

            if payload.pop("recordType", None) == "generated-asset":
                result = GeneratedAssetService(self.pipeline.workspace).register(
                    payload.pop("record")
                )
            else:
                service = ComponentInstanceService(self.pipeline.workspace)
                instance = service.register(
                    payload.pop("instance"),
                    parameter_schema=payload.pop("parameterSchema", None),
                )
                result = {"instance": instance}
                adapter_id = payload.pop("adapterId", None)
                if adapter_id:
                    result["implementationRef"] = service.implementation_reference(
                        instance["instanceId"],
                        adapter_id=str(adapter_id),
                        kind=str(payload.pop("kind", "project-component")),
                    )
        elif command in {"sound", "media", "captions", "color", "grade", "end-screen"}:
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
