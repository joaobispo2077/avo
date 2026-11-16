"""Compile immutable proof orchestration from canonical JSON authority."""

from __future__ import annotations

import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

from avo.capabilities import CapabilityRegistry, default_proof_capability_registry

from .contracts import (
    ContractError,
    content_hash,
    document_hash_excluding,
    file_fingerprint,
    validate_document,
    validate_proof_plan_document,
)
from .iterations import IterationLedgerService
from .store import StoreError, write_immutable_json


def _preview_declaration(request):
    return {
        key: deepcopy(request[key])
        for key in ("previewOnly", "importApproximation")
        if key in request
    }


def _proof_contract_header(camera_operations):
    if camera_operations:
        return {
            "schemaVersion": "2.0.0",
            "requiredReaderCapabilities": ["camera-transform-v1"],
        }
    return {"schemaVersion": "1.0.0"}


def _require_hyperframes_geometry(binding, parameters, output):
    canvas = binding["canonicalCanvas"]
    rate = output["frameRate"]
    canonical_rate = binding["renderContract"]["frameRate"]
    if Fraction(rate["num"], rate["den"]) != Fraction(
        canonical_rate["num"], canonical_rate["den"]
    ):
        raise ValueError("HyperFrames proof changes the canonical frame rate")
    scale = Fraction(output["width"], canvas["width"])
    if scale != Fraction(output["height"], canvas["height"]):
        raise ValueError("HyperFrames preview changes canonical canvas aspect ratio")
    placement = {}
    for key in ("x", "y", "width", "height"):
        value = Fraction(binding["placement"][key]) * scale
        if value.denominator != 1:
            raise ValueError("HyperFrames placement is not preview-pixel aligned")
        placement[key] = int(value)
    if (
        parameters["placement"] != placement
        or parameters["zOrder"] != binding["placement"]["zOrder"]
        or parameters["layerRole"] != binding["placement"]["layerRole"]
    ):
        raise ValueError("HyperFrames placement/order differs from canonical Tracks")


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

    def _import_assembly(self, request):
        store = self.workspace.store("cmap")
        index = store.load_index()
        if not index["headRevisionId"]:
            return {}
        revision = store.revision(index["headRevisionId"])
        snapshot = revision["snapshot"]
        if snapshot.get("sourceAssemblyPolicy") != "preserve-import":
            return {}
        from .resolve_export import require_renderable_import

        try:
            require_renderable_import(
                snapshot,
                approximation=request.get("importApproximation"),
                preview_only=request.get("previewOnly", False),
            )
        except ValueError as exc:
            raise ProofPlanError(
                "PROOF_IMPORT_TREATMENT_UNSUPPORTED",
                str(exc),
                "Retained imported treatments need renderer support before a strict proof can be produced. Continue editing the structural draft in AVO.",
            ) from exc
        self._verify_import_sources(revision)
        self._require_import_output(request["output"], snapshot["importOutput"])
        if request.get("checkpoint") == "cut-proof":
            self._require_preserved_source_graph(request)
        return {
            "sourceAssemblyPolicy": "preserve-import",
            "importOriginRef": deepcopy(snapshot["originRef"]),
            "importOutput": deepcopy(snapshot["importOutput"]),
        }

    def _verify_import_sources(self, revision):
        from .import_evidence import verify_import_origin
        from .media_admission import require_no_forbidden_outputs
        from .migration import inventory_historical_output_fingerprints

        try:
            verify_import_origin(self.workspace, revision)
            require_no_forbidden_outputs(
                revision["snapshot"]["sources"],
                known_outputs=inventory_historical_output_fingerprints(
                    self.workspace.raw_dir, timeline_dir=self.workspace.timeline_dir
                ),
            )
        except ValueError as exc:
            raise ProofPlanError(
                "PROOF_IMPORT_EVIDENCE_INVALID",
                str(exc),
                "Restore the exact activated import evidence and fingerprinted originals; revalidate unresolved imports",
            ) from exc

    @staticmethod
    def _require_import_output(output, canonical):
        clocks = (
            Fraction(output["frameRate"]["num"], output["frameRate"]["den"])
            == Fraction(canonical["frameRate"]["num"], canonical["frameRate"]["den"]),
            output["audioSampleRate"] == canonical["audioSampleRate"],
            output["channelLayout"] == canonical["channelLayout"],
            output["width"] * canonical["height"]
            == output["height"] * canonical["width"],
        )
        if not all(clocks):
            raise ProofPlanError(
                "PROOF_IMPORT_OUTPUT_CHANGED",
                "Proof output changes canonical imported clocks, routing or canvas aspect ratio",
                "Use the imported output settings; author an explicit canonical change before changing them",
            )

    def _require_preserved_source_graph(self, request):
        from .initial_cut import initial_cut_proof_request

        output = request["output"]
        expected = initial_cut_proof_request(
            self.workspace,
            iteration_id=request["iterationId"],
            output=Path(output["path"]),
            frame_rate=output["frameRate"],
            width=output["width"],
            height=output["height"],
            sample_rate=output["audioSampleRate"],
            import_approximation=request.get("importApproximation"),
        )
        requested = deepcopy(request)
        for operation in requested["videoGraph"]["operations"]:
            operation.pop("implementationId", None)
        if any(
            requested[key] != expected[key]
            for key in ("videoGraph", "audioGraph", "events")
        ):
            raise ProofPlanError(
                "PROOF_IMPORT_ASSEMBLY_CHANGED",
                "Cut-proof graph changes the canonical imported source assembly",
                "Author an explicit canonical edit before compiling a changed source reconstruction",
            )

    def _import_preflight(self, plan):
        try:
            expected = self._import_assembly(plan)
            if any(plan.get(key) != value for key, value in expected.items()):
                raise ProofPlanError(
                    "PROOF_IMPORT_ASSEMBLY_CHANGED",
                    "Proof policy/origin does not match the canonical import",
                    "Compile a new proof plan from the current canonical cut",
                )
        except ProofPlanError as exc:
            return [exc.to_dict()]
        except (StoreError, KeyError, ValueError, RuntimeError):
            # Canonical preflight reports missing/invalid authority separately.
            return [
                self._blocker(
                    "PROOF_IMPORT_ASSEMBLY_CHANGED",
                    "Cannot verify canonical import preservation",
                    "Restore current canonical authority and compile again",
                )
            ]
        return []

    def _source_mix_graph(self, request, *, require_applied=False):
        if request.get("checkpoint", "pre-master") == "cut-proof":
            return deepcopy(request["audioGraph"])
        index = self.workspace.require_active("tracks")
        tracks = self.workspace.store("tracks").revision(index["headRevisionId"])[
            "snapshot"
        ]
        audio = tracks.get("audioTracks") or {}
        if "sourceMixAdjustments" not in audio:
            return deepcopy(request["audioGraph"])
        if audio["sourceMixAdjustments"] == []:
            return deepcopy(request["audioGraph"])
        from .initial_cut import initial_cut_proof_request
        from .source_mix import apply_source_mix_adjustments

        cmap_index = self.workspace.require_active("cmap")
        cmap = self.workspace.store("cmap").revision(cmap_index["headRevisionId"])[
            "snapshot"
        ]
        output = request["output"]
        try:
            base = initial_cut_proof_request(
                self.workspace,
                iteration_id=request["iterationId"],
                output=Path(output["path"]),
                frame_rate=output["frameRate"],
                width=output["width"],
                height=output["height"],
                sample_rate=output["audioSampleRate"],
            )
            return apply_source_mix_adjustments(
                cmap,
                base["audioGraph"],
                request["audioGraph"],
                audio["sourceMixAdjustments"],
                require_applied=require_applied,
            )
        except (ValueError, KeyError, TypeError) as error:
            raise ProofPlanError(
                "PROOF_SOURCE_MIX_INVALID",
                str(error),
                "Restore exact source-mix targets and compile once from the canonical base audio graph",
            ) from error

    def _source_mix_preflight(self, plan):
        try:
            self._source_mix_graph(plan, require_applied=True)
        except (ValueError, RuntimeError, KeyError, TypeError) as error:
            return [
                self._blocker(
                    "PROOF_SOURCE_MIX_INVALID",
                    str(error),
                    "Compile a fresh proof plan from the current canonical source mix",
                )
            ]
        return []

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

    def _camera_operations(self, request, checkpoint, lock):
        if checkpoint == "cut-proof":
            return []
        from .contracts import required_animation_readers

        if any(
            operation.get("kind") == "camera-transform"
            for operation in request.get("videoGraph", {}).get("operations", [])
        ):
            raise ProofPlanError(
                "PROOF_CAMERA_AUTHORITY",
                "Camera operations must derive from the canonical selected strategy.",
                "Revise the selected camera component instead of injecting execution operations.",
            )
        store = self.workspace.store("animation")
        index = store.load_index()
        if index["headRevisionId"] is None:
            return []
        snapshot = store.revision(index["headRevisionId"])["snapshot"]
        if not required_animation_readers(snapshot):
            return []
        if (
            self.registry.resolve(
                "camera-transform-v1", implementation_id="impl-camera-transform"
            )
            is None
        ):
            raise ProofPlanError(
                "PROOF_CAMERA_UNAVAILABLE",
                "Selected camera intent requires the qualified camera proof implementation.",
                "Keep the camera intent pending until source-picture execution is qualified; do not render a v1 no-op.",
            )
        self._camera_basis(snapshot, lock)
        operations = self._compile_camera_operations(snapshot, request)
        for operation in operations:
            parameters = operation["parameters"]
            if (
                lock.get("source:" + parameters["sourceId"])
                != parameters["sourceSha256"]
            ):
                raise ProofPlanError(
                    "PROOF_CAMERA_SOURCE_CHANGED",
                    "Camera source fingerprint differs from the exact proof source lock.",
                    "Restore the selected original or revise the camera against its new source.",
                )
        return operations

    @staticmethod
    def _camera_basis(snapshot, lock):
        for name in ("cmap", "bmap", "tracks"):
            if snapshot.get("dependencies", {}).get(name) != lock[name]:
                raise ProofPlanError(
                    "PROOF_CAMERA_BASIS_CHANGED",
                    "Camera intent has a stale canonical " + name + " basis.",
                    "Rebase and review the selected camera intent before compiling.",
                )

    def _compile_camera_operations(self, snapshot, request):
        from .camera_plan import compile_camera_operations

        def current(name):
            store = self.workspace.store(name)
            return store.revision(store.load_index()["headRevisionId"])["snapshot"]

        try:
            validate_document(
                request["output"], "avo.proof-plan.v2.schema.json#/$defs/output"
            )
            return compile_camera_operations(
                snapshot,
                bmap=current("bmap"),
                tracks=current("tracks"),
                video_graph=request.get("videoGraph", {}),
                output=request["output"],
                selection=None,
            )
        except ValueError as error:
            raise ProofPlanError(
                "PROOF_CAMERA_INVALID",
                str(error),
                "Resolve the selected camera's frozen options, source geometry, cue and continuity.",
            ) from error

    def _require_recorded_motion_implementation(self, implementation):
        if not implementation.adapter_id.startswith("hyperframes"):
            return
        index = self.workspace.store("animation").load_index()
        if index["headRevisionId"] is None:
            return
        snapshot = self.workspace.store("animation").revision(index["headRevisionId"])[
            "snapshot"
        ]
        engine = snapshot.get("framework", "hyperframes")
        if engine != "hyperframes":
            raise ProofPlanError(
                "PROOF_ENGINE_INCOMPATIBLE",
                f"HyperFrames capability is incompatible with recorded {engine} animation.",
                "Use admitted generated-clip/overlay-video operations for code-drawn; engine selection does not convert provider kits.",
            )

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
            self._require_recorded_motion_implementation(implementation)
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

    def _generated_receipt(self, reference):
        from .generated_assets import GeneratedAssetService

        record = GeneratedAssetService(self.workspace).load(reference["assetId"])
        if reference["recordHash"] != record["recordHash"]:
            raise ValueError("Generated record changed before proof compilation")
        receipt = Path(reference["locator"])
        if json.loads(receipt.read_text(encoding="utf-8")) != record:
            raise ValueError(f"Generated receipt differs: {receipt}")
        return record

    @staticmethod
    def _generated_original_lock(parameters):
        input_ref = parameters["inputLockRef"]
        input_path = Path(input_ref["path"])
        if file_fingerprint(input_path)["sha256"] != input_ref["sha256"]:
            raise ValueError(f"Generated input lock changed: {input_path}")
        return json.loads(input_path.read_text(encoding="utf-8"))

    @staticmethod
    def _require_generated_output(record, parameters):
        actual = file_fingerprint(Path(record["output"]["locator"]))
        if any(actual[key] != record["output"][key] for key in ("sha256", "sizeBytes")):
            raise ValueError("Generated output fingerprint changed")
        if any(
            parameters["sourceFingerprint"].get(key) != record["output"].get(key)
            for key in ("locator", "sha256", "sizeBytes")
        ):
            raise ValueError("Generated operation source differs from its receipt")

    @staticmethod
    def _require_drawing_operation_geometry(operation, original):
        parameters = operation["parameters"]
        if operation["outputRange"] != original["range"]:
            raise ValueError("Generated output range differs from canonical Tracks")
        expected = {
            "startFrame": 0,
            "endFrameExclusive": original["range"]["endFrameExclusive"]
            - original["range"]["startFrame"],
        }
        if parameters["sourceRange"] != expected:
            raise ValueError("Generated source range differs from canonical drawing")
        if operation["kind"] != "overlay-video":
            return
        if any(
            parameters.get(key) != original["placement"][key]
            for key in ("zOrder", "layerRole")
        ):
            raise ValueError(
                "Generated overlay role/order differs from canonical Tracks"
            )
        if parameters.get("placement") != {
            key: original["placement"][key] for key in ("x", "y", "width", "height")
        }:
            raise ValueError(
                "Generated overlay placement differs from canonical Tracks"
            )

    def _require_canonical_generated(self, operation, record, original):
        from avo.motion import verify_code_drawn_lock

        extension = record["parameters"]["codeDrawn"]
        if original["bindingMode"] != "canonical":
            raise ValueError("Code-drawn proof input requires canonical binding")
        composition = Path(extension["manifestRef"]["path"])
        if not composition.is_absolute():
            composition = self.workspace.raw_dir / composition
        verify_code_drawn_lock(composition, original, workspace=self.workspace)
        self._require_drawing_operation_geometry(operation, original)
        if extension["inputLockRef"] != operation["parameters"]["inputLockRef"]:
            raise ValueError(
                "Frozen input-lock reference differs from the generated receipt"
            )

    def _require_hyperframes_generated(self, operation, record, original, output):
        from .hyperframes_binding import verify_binding

        binding = original["binding"]
        verify_binding(self.workspace, binding)
        extension = record["parameters"]["hyperframes"]
        parameters = operation["parameters"]
        if (
            extension["instanceHash"] != binding["instanceHash"]
            or extension["canonicalInputLock"] != binding["canonicalInputLock"]
            or extension["inputLockRef"] != parameters["inputLockRef"]
            or operation["kind"] != "overlay-video"
            or operation["outputRange"] != binding["range"]
            or parameters["sourceRange"]
            != {
                "startFrame": 0,
                "endFrameExclusive": binding["renderContract"]["frameCount"],
            }
        ):
            raise ValueError("HyperFrames operation differs from canonical binding")
        _require_hyperframes_geometry(binding, parameters, output)

    def _generated_lock(self, graph: dict[str, Any], output=None) -> dict[str, str]:
        """Bind generated receipts and original locks without rewriting them."""
        lock = {}
        for operation in graph.get("operations") or []:
            parameters = operation.get("parameters") or {}
            reference = parameters.get("generatedAssetRef")
            if not reference:
                continue
            record = self._generated_receipt(reference)
            original = self._generated_original_lock(parameters)
            self._require_generated_output(record, parameters)
            if record.get("parameters", {}).get("codeDrawn"):
                self._require_canonical_generated(operation, record, original)
            if record.get("parameters", {}).get("hyperframes"):
                self._require_hyperframes_generated(operation, record, original, output)
            lock["generated:" + record["assetId"]] = record["recordHash"]
            lock["input-lock:" + original["instanceId"]] = original["inputLockHash"]
        return lock

    def _generated_preflight(self, plan, readiness):
        blockers = []
        try:
            current = self._generated_lock(plan["videoGraph"], plan["output"])
            frozen = plan["canonicalInputLock"]
            if any(frozen.get(key) != value for key, value in current.items()):
                raise ValueError(
                    "Generated receipt/input-lock differs from the frozen proof plan"
                )
            for key in current:
                if key.startswith("generated:") and readiness.get(key) is not True:
                    raise ValueError(
                        f"Current generated asset admission is required: {key}"
                    )
        except (ValueError, OSError, KeyError) as error:
            blockers.append(
                self._blocker(
                    "PROOF_GENERATED_ASSET_STALE",
                    str(error),
                    "Rematerialize or restore exact drawing sources and rerun selected-runtime admission.",
                )
            )
        return blockers

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
        camera_operations = self._camera_operations(request, checkpoint, lock)
        request.setdefault("videoGraph", {}).setdefault("operations", []).extend(
            camera_operations
        )
        audio_graph = self._source_mix_graph(request)
        video_graph, resolution, implementation_refs = self._resolve_video_graph(
            dict(request.get("videoGraph") or {})
        )
        lock.update(self._generated_lock(video_graph, request["output"]))
        body: dict[str, Any] = {
            **_proof_contract_header(camera_operations),
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
            "audioGraph": audio_graph,
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
        body.update(self._import_assembly(request))
        identity_seed = deepcopy(body)
        identity_seed.pop("proofPlanHash", None)
        identity_seed.pop("proofPlanId", None)
        body["proofPlanId"] = f"proof-plan-{content_hash(identity_seed)[:12]}"
        body["proofPlanHash"] = document_hash_excluding(body, "proofPlanHash")
        try:
            validate_proof_plan_document(body)
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
            validate_proof_plan_document(value)
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
        tool_readiness: dict[str, Any],
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
        blockers.extend(self._import_preflight(plan))
        blockers.extend(self._source_mix_preflight(plan))
        blockers.extend(self._generated_preflight(plan, tool_readiness))
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
        from .workspace import TimelineWorkspace

        learning = TimelineWorkspace.provider_learning_diagnostic(self.workspace)
        report = {
            "schemaVersion": "1.0.0",
            "proofPlanId": plan.get("proofPlanId"),
            "proofPlanHash": plan.get("proofPlanHash"),
            "status": "blocked" if blockers else "pass",
            "blockers": blockers,
            "providerLearning": {
                "status": learning["status"],
                "warnings": learning["warnings"],
                "loadedFinalSnapshots": learning["loadedFinalSnapshots"],
                "snapshots": [
                    {
                        "snapshotId": item["snapshotId"],
                        "snapshotHash": item["snapshotHash"],
                        "preventionRules": deepcopy(item.get("preventionRules") or []),
                        "taxonomy": deepcopy(item.get("taxonomy") or []),
                    }
                    for item in learning["snapshots"]
                ],
                "binding": False,
                "inheritedApprovals": False,
            },
        }
        self._bind_camera_environment(report, plan, tool_readiness)
        report["reportHash"] = content_hash(report)
        return report

    def _bind_camera_environment(self, report, plan, tool_readiness):
        if any(
            operation.get("kind") == "camera-transform"
            for operation in plan.get("videoGraph", {}).get("operations", [])
        ):
            environment = tool_readiness.get("cameraEnvironmentHash")
            if (
                tool_readiness.get("camera-runtime") is not True
                or not isinstance(environment, str)
                or len(environment) != 64
                or any(character not in "0123456789abcdef" for character in environment)
            ):
                report["blockers"].append(
                    self._blocker(
                        "PROOF_CAMERA_RUNTIME_UNBOUND",
                        "Selected camera runtime lacks an observed rendering environment",
                        "Use the native camera renderer to inspect installed tools before preflight",
                    )
                )
                report["status"] = "blocked"
            else:
                report["cameraEnvironmentHash"] = environment

    def require_preflight(
        self,
        plan: dict[str, Any],
        *,
        media_inputs: dict[str, Any],
        tool_readiness: dict[str, Any],
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
