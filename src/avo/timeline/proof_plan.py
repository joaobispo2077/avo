"""Compile immutable proof orchestration from canonical JSON authority."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from avo.capabilities import CapabilityRegistry, default_proof_capability_registry

from .contracts import (
    ContractError,
    content_hash,
    document_hash_excluding,
    file_fingerprint,
    validate_document,
)
from .iterations import IterationLedgerService
from .store import StoreError, write_immutable_json


def _preview_declaration(request):
    return {"previewOnly": request["previewOnly"]} if "previewOnly" in request else {}


class ProofPlanError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        remediation: str,
        *,
        entity_ref: str | None = None,
        expected: Any = None,
        actual: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.remediation = remediation
        self.entity_ref = entity_ref
        self.expected = expected
        self.actual = actual

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "remediation": self.remediation,
            "blocking": True,
            "entityRef": self.entity_ref,
            "expected": self.expected,
            "actual": self.actual,
        }


class ProofPlanCompiler:
    CANONICAL_ARTIFACTS = ("cmap", "bmap", "tracks", "animation", "sync-map")
    CUT_OPTIONAL_ARTIFACTS = ("bmap", "tracks", "animation")

    def __init__(self, workspace: Any, registry: CapabilityRegistry | None = None):
        self.workspace = workspace
        self.registry = registry or default_proof_capability_registry()
        self.directory = Path(workspace.timeline_dir) / "proof-plans"

    @staticmethod
    def _empty_index(index: dict[str, Any]) -> bool:
        return (
            index.get("headRevisionId") is None
            and index.get("approvedRevisionId") is None
            and not index.get("revisionRefs")
            and not index.get("eventRefs")
            and index.get("activeState") == "valid"
        )

    def _canonical_lock(
        self, source_fingerprints: dict[str, str], *, checkpoint: str
    ) -> dict[str, str]:
        if not source_fingerprints:
            raise ProofPlanError(
                "PROOF_SOURCE_LOCK_REQUIRED",
                "proof planning requires fingerprinted source media",
                "provide every source identity used by the canonical timeline",
            )
        lock: dict[str, str] = {}
        for artifact_type in self.CANONICAL_ARTIFACTS:
            if (
                checkpoint == "cut-proof"
                and artifact_type in self.CUT_OPTIONAL_ARTIFACTS
            ):
                index = self.workspace.store(artifact_type).load_index()
                if self._empty_index(index):
                    lock[f"absent:{artifact_type}"] = content_hash(index)
                    continue
            index = self.workspace.require_active(artifact_type)
            revision = self.workspace.store(artifact_type).revision(
                index["headRevisionId"]
            )
            lock[artifact_type] = str(revision["contentHash"])
        for source_id, sha256 in sorted(source_fingerprints.items()):
            lock[f"source:{source_id}"] = str(sha256)
        return lock

    def _resolve_video_graph(
        self, graph: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        operations: list[dict[str, Any]] = []
        resolution: list[dict[str, Any]] = []
        refs: dict[str, dict[str, Any]] = {}
        gaps: list[str] = []
        for requested in graph.get("operations") or []:
            operation = deepcopy(requested)
            capability = str(operation.pop("capability", operation.get("kind") or ""))
            requested_id = operation.get("implementationId")
            implementation = self.registry.resolve(
                capability,
                implementation_id=str(requested_id) if requested_id else None,
            )
            if implementation is None:
                operation_id = str(operation.get("operationId") or "unknown-operation")
                gaps.append(f"{operation_id}:{capability}")
                resolution.append(
                    {
                        "operationId": operation_id,
                        "capability": capability,
                        "implementationId": "impl-unsupported",
                        "status": "unsupported",
                    }
                )
                continue
            operation["implementationId"] = implementation.implementation_id
            operations.append(operation)
            resolution.append(
                {
                    "operationId": operation["operationId"],
                    "capability": capability,
                    "implementationId": implementation.implementation_id,
                    "status": "resolved",
                }
            )
            refs[implementation.implementation_id] = implementation.proof_reference()
        if gaps:
            raise ProofPlanError(
                "PROOF_CAPABILITY_GAP",
                "proof operations have no registered compatible implementation: "
                + ", ".join(gaps),
                "register only the unsupported custom delta, then compile a new "
                "proof plan",
                entity_ref=gaps[0].split(":", 1)[0],
                expected="registered compatible capability",
                actual=gaps,
            )
        return {"operations": operations}, resolution, list(refs.values())

    @staticmethod
    def _contract_for_plan(contract: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(contract)
        value["historicalRiskWindows"] = [
            {
                "startFrame": item["startFrame"],
                "endFrameExclusive": item["endFrameExclusive"],
            }
            for item in value.get("historicalRiskWindows") or []
        ]
        return value

    def compile(
        self,
        request: dict[str, Any],
        *,
        regression_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = deepcopy(request)
        iteration_id = str(request["iterationId"])
        contract = regression_contract or IterationLedgerService(
            self.workspace
        ).compile_regression_contract(iteration_id)
        if contract.get("conflicts"):
            raise ProofPlanError(
                "PROOF_REGRESSION_CONFLICT",
                "regression contract contains unresolved human conflicts",
                "resolve or supersede the conflicting decisions before planning",
                entity_ref=str(contract.get("contractId")),
                actual=contract["conflicts"],
            )
        checkpoint = str(request.get("checkpoint", "pre-master"))
        lock = self._canonical_lock(
            dict(request.get("sourceFingerprints") or {}), checkpoint=checkpoint
        )
        video_graph, resolution, implementation_refs = self._resolve_video_graph(
            dict(request.get("videoGraph") or {})
        )
        body: dict[str, Any] = {
            "schemaVersion": "1.0.0",
            "proofPlanId": "proof-plan-pending",
            "iterationId": iteration_id,
            "checkpoint": checkpoint,
            "canonicalInputLock": lock,
            "regressionContract": self._contract_for_plan(contract),
            "renderProfile": str(request["renderProfile"]),
            "output": deepcopy(request["output"]),
            "capabilityResolution": resolution,
            "implementationRefs": sorted(
                implementation_refs, key=lambda item: item["implementationId"]
            ),
            "videoGraph": video_graph,
            "audioGraph": deepcopy(request["audioGraph"]),
            "events": deepcopy(request.get("events") or []),
            "validationPlan": deepcopy(request["validationPlan"]),
            "visionReviewPlanRef": deepcopy(request.get("visionReviewPlanRef")),
            "lineagePolicy": deepcopy(
                request.get("lineagePolicy")
                or {
                    "allowedMediaClasses": ["source", "generated-asset"],
                    "prohibitedMediaClasses": [
                        "proof",
                        "preview",
                        "proxy",
                        "master",
                        "delivery",
                    ],
                    "recursive": True,
                }
            ),
            "producer": deepcopy(
                request.get("producer")
                or {
                    "name": "avo",
                    "version": "development",
                    "compiler": "canonical-proof-plan",
                }
            ),
            "proofPlanHash": "",
        }
        body.update(_preview_declaration(request))
        identity_seed = deepcopy(body)
        identity_seed.pop("proofPlanHash", None)
        identity_seed.pop("proofPlanId", None)
        body["proofPlanId"] = f"proof-plan-{content_hash(identity_seed)[:12]}"
        body["proofPlanHash"] = document_hash_excluding(body, "proofPlanHash")
        try:
            validate_document(body, "avo.proof-plan.schema.json")
        except ContractError as exc:
            raise ProofPlanError(
                "PROOF_PLAN_INVALID",
                f"compiled proof plan violates its contract: {exc}",
                "fix the canonical operation or output request and compile again",
                entity_ref=body["proofPlanId"],
            ) from exc
        try:
            write_immutable_json(self.path(body["proofPlanId"]), body)
        except StoreError as exc:
            raise ProofPlanError(
                "PROOF_PLAN_IMMUTABLE_CONFLICT",
                str(exc),
                "compile a new proof plan from the updated canonical inputs",
                entity_ref=body["proofPlanId"],
            ) from exc
        return deepcopy(body)

    def path(self, proof_plan_id: str) -> Path:
        return self.directory / f"{proof_plan_id}.json"

    def load(self, path_or_id: str | Path) -> dict[str, Any]:
        path = Path(path_or_id)
        if not path.is_file():
            path = self.path(str(path_or_id))
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProofPlanError(
                "PROOF_PLAN_NOT_FOUND",
                f"cannot load proof plan: {exc}",
                "provide the path or ID of an immutable compiled proof plan",
            ) from exc
        if value.get("proofPlanHash") != document_hash_excluding(
            value, "proofPlanHash"
        ):
            raise ProofPlanError(
                "PROOF_PLAN_HASH_MISMATCH",
                "proof plan content changed after compilation",
                "restore the immutable plan or compile a new one",
                entity_ref=str(value.get("proofPlanId") or ""),
            )
        try:
            validate_document(value, "avo.proof-plan.schema.json")
        except ContractError as exc:
            raise ProofPlanError(
                "PROOF_PLAN_INVALID",
                f"immutable proof plan violates its contract: {exc}",
                "restore the original plan or compile a new one",
                entity_ref=str(value.get("proofPlanId") or ""),
            ) from exc
        return value

    @staticmethod
    def _blocker(
        code: str,
        message: str,
        remediation: str,
        *,
        entity_ref: str | None = None,
        expected: Any = None,
        actual: Any = None,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "message": message,
            "remediation": remediation,
            "blocking": True,
            "entityRef": entity_ref,
            "expected": expected,
            "actual": actual,
        }

    def _absence_matches(self, plan, artifact_type, lock):
        absent_key = f"absent:{artifact_type}"
        try:
            index = self.workspace.store(artifact_type).load_index()
            return (
                plan.get("checkpoint") == "cut-proof"
                and artifact_type in self.CUT_OPTIONAL_ARTIFACTS
                and self._empty_index(index)
                and artifact_type not in lock
                and lock[absent_key] == content_hash(index)
            )
        except Exception:
            return False

    def _canonical_preflight(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        blockers = []
        lock = plan.get("canonicalInputLock") or {}
        for artifact_type in self.CANONICAL_ARTIFACTS:
            absent_key = f"absent:{artifact_type}"
            if absent_key in lock:
                valid_absence = self._absence_matches(plan, artifact_type, lock)
                if not valid_absence:
                    blockers.append(
                        self._blocker(
                            "PROOF_REVISION_STALE",
                            f"canonical {artifact_type} absence no longer matches the proof plan",
                            "compile a new proof plan from the current canonical state",
                            entity_ref=artifact_type,
                        )
                    )
                continue
            try:
                index = self.workspace.require_active(artifact_type)
                revision = self.workspace.store(artifact_type).revision(
                    index["headRevisionId"]
                )
                actual = revision["contentHash"]
            except Exception as exc:
                blockers.append(
                    self._blocker(
                        "PROOF_REVISION_UNAVAILABLE",
                        f"canonical {artifact_type} head is unavailable: {exc}",
                        "restore or revalidate the canonical revision",
                        entity_ref=artifact_type,
                    )
                )
                continue
            expected = lock.get(artifact_type)
            if expected != actual:
                blockers.append(
                    self._blocker(
                        "PROOF_REVISION_STALE",
                        f"canonical {artifact_type} no longer matches the proof plan",
                        "compile a new proof plan from the current canonical heads",
                        entity_ref=artifact_type,
                        expected=expected,
                        actual=actual,
                    )
                )
        return blockers

    def _implementation_preflight(self, plan):
        blockers = []
        native_registry = default_proof_capability_registry()
        for item in plan.get("implementationRefs") or []:
            implementation_id = str(item.get("implementationId") or "")
            native = next(
                (
                    implementation
                    for implementation in native_registry.implementations()
                    if implementation.implementation_id == implementation_id
                ),
                None,
            )
            if (
                item.get("kind") == "built-in"
                and native is not None
                and item != native.proof_reference()
            ):
                blockers.append(
                    self._blocker(
                        "PROOF_IMPLEMENTATION_STALE",
                        f"native implementation changed: {implementation_id}",
                        "compile a new proof plan with the current implementation",
                        entity_ref=implementation_id,
                        expected=item.get("sha256"),
                        actual=native.sha256,
                    )
                )
        return blockers

    def preflight(
        self,
        plan: dict[str, Any],
        *,
        media_inputs: dict[str, Any],
        tool_readiness: dict[str, bool],
    ) -> dict[str, Any]:
        """Return deterministic blockers before any microproof or full render."""
        blockers: list[dict[str, Any]] = []
        if plan.get("proofPlanHash") != document_hash_excluding(plan, "proofPlanHash"):
            blockers.append(
                self._blocker(
                    "PROOF_PLAN_HASH_MISMATCH",
                    "proof plan bytes changed after compilation",
                    "restore the immutable plan or compile a new plan",
                    entity_ref=str(plan.get("proofPlanId") or ""),
                )
            )
        blockers.extend(self._canonical_preflight(plan))
        lock = plan.get("canonicalInputLock") or {}
        resolved_paths: dict[str, Path] = {}
        for key, expected in sorted(lock.items()):
            if not key.startswith("source:"):
                continue
            source_id = key.removeprefix("source:")
            media_input = media_inputs.get(source_id)
            if media_input is None:
                blockers.append(
                    self._blocker(
                        "PROOF_MEDIA_MISSING",
                        f"source media is not registered for {source_id}",
                        "provide the fingerprinted source locator",
                        entity_ref=source_id,
                    )
                )
                continue
            if isinstance(media_input, dict):
                locator = media_input.get("path") or media_input.get("locator")
                classes = {
                    str(media_input.get("mediaClass") or ""),
                    *(
                        str(item.get("mediaClass") or "")
                        for item in media_input.get("ancestry") or []
                        if isinstance(item, dict)
                    ),
                }
            else:
                locator = media_input
                classes = set()
            prohibited = set(
                (plan.get("lineagePolicy") or {}).get("prohibitedMediaClasses") or []
            )
            forbidden = sorted(classes.intersection(prohibited))
            if forbidden:
                blockers.append(
                    self._blocker(
                        "PROOF_FORBIDDEN_MEDIA_ANCESTRY",
                        f"source {source_id} descends from forbidden media",
                        "replace it with an original or admitted canonical source",
                        entity_ref=source_id,
                        actual=forbidden,
                    )
                )
            if not locator:
                blockers.append(
                    self._blocker(
                        "PROOF_MEDIA_MISSING",
                        f"source media locator is empty for {source_id}",
                        "provide the fingerprinted source locator",
                        entity_ref=source_id,
                    )
                )
                continue
            path = Path(locator).resolve()
            resolved_paths[source_id] = path
            if not path.is_file():
                blockers.append(
                    self._blocker(
                        "PROOF_MEDIA_MISSING",
                        f"source media does not exist: {path}",
                        "restore the source at its registered locator",
                        entity_ref=source_id,
                    )
                )
                continue
            actual = file_fingerprint(path)["sha256"]
            if actual != expected:
                blockers.append(
                    self._blocker(
                        "PROOF_DEPENDENCY_LOCK_MISMATCH",
                        f"source fingerprint changed for {source_id}",
                        "restore the exact source or compile a new proof plan",
                        entity_ref=source_id,
                        expected=expected,
                        actual=actual,
                    )
                )
        output = Path(str((plan.get("output") or {}).get("path") or "")).resolve()
        aliases = [
            source_id for source_id, path in resolved_paths.items() if path == output
        ]
        if aliases:
            blockers.append(
                self._blocker(
                    "PROOF_OUTPUT_ALIASES_INPUT",
                    "proof output aliases source media",
                    "choose an output path outside every source locator",
                    entity_ref=aliases[0],
                    actual=str(output),
                )
            )
        refs = {
            item.get("implementationId")
            for item in plan.get("implementationRefs") or []
        }
        for item in plan.get("capabilityResolution") or []:
            if (
                item.get("status") != "resolved"
                or item.get("implementationId") not in refs
            ):
                blockers.append(
                    self._blocker(
                        "PROOF_CAPABILITY_GAP",
                        f"operation {item.get('operationId')} is not fully resolved",
                        "register a compatible implementation and compile a new plan",
                        entity_ref=str(item.get("operationId") or ""),
                    )
                )
        required_tools: set[str] = {"proof-plan-executor"}
        blockers.extend(self._implementation_preflight(plan))
        for item in plan.get("implementationRefs") or []:
            adapter = str(item.get("adapterId") or "").casefold()
            if "ffmpeg" in adapter:
                required_tools.add("ffmpeg")
            if "hyperframes" in adapter:
                required_tools.add("hyperframes")
        for tool in sorted(required_tools):
            if tool_readiness.get(tool) is not True:
                blockers.append(
                    self._blocker(
                        "PROOF_TOOL_NOT_READY",
                        f"required proof tool is not ready: {tool}",
                        f"install or repair {tool}, then rerun preflight",
                        entity_ref=tool,
                        expected=True,
                        actual=tool_readiness.get(tool),
                    )
                )
        learning_loader = getattr(self.workspace, "finalized_provider_learning", list)
        report = {
            "schemaVersion": "1.0.0",
            "proofPlanId": plan.get("proofPlanId"),
            "proofPlanHash": plan.get("proofPlanHash"),
            "status": "blocked" if blockers else "pass",
            "blockers": blockers,
            "providerLearning": {
                "snapshots": [
                    {
                        "snapshotId": item["snapshotId"],
                        "snapshotHash": item["snapshotHash"],
                        "preventionRules": deepcopy(item.get("preventionRules") or []),
                        "taxonomy": deepcopy(item.get("taxonomy") or []),
                    }
                    for item in learning_loader()
                ],
                "binding": False,
                "inheritedApprovals": False,
            },
        }
        report["reportHash"] = content_hash(report)
        return report

    def require_preflight(
        self,
        plan: dict[str, Any],
        *,
        media_inputs: dict[str, Any],
        tool_readiness: dict[str, bool],
    ) -> dict[str, Any]:
        report = self.preflight(
            plan,
            media_inputs=media_inputs,
            tool_readiness=tool_readiness,
        )
        if report["blockers"]:
            blocker = report["blockers"][0]
            raise ProofPlanError(
                blocker["code"],
                blocker["message"],
                blocker["remediation"],
                entity_ref=blocker.get("entityRef"),
                expected=blocker.get("expected"),
                actual=blocker.get("actual"),
            )
        return report
