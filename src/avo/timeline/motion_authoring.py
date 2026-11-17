"""Untimed concepts, exact creator selections and recoverable canonical apply."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from avo.editing_craft import validate_editing_craft_selection

from .animation import AnimationService
from .bmap_service import BMapService
from .cmap_service import CMapService
from .contracts import content_hash, fingerprint_stage, validate_document
from .lifecycle import PipelineRunStore
from .motion_review import METADATA_LIMITS, MotionReviewService, _check_budget
from .store import (
    atomic_write_json,
    motion_application_access,
    timeline_writer,
    write_immutable_json,
)
from .tracks import TracksService

SCHEMA = "avo.motion-proposal.schema.json"
MAX_BYTES = 4 * 1024 * 1024
OWNERS = {"bmap": BMapService, "tracks": TracksService, "animation": AnimationService}


class MotionAuthoringError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

    def to_dict(self):
        return {
            "code": self.code,
            "message": str(self),
            "blocking": True,
            "remediation": "Inspect the exact proposal, source basis and pending recovery before retrying.",
        }


def _validate(value, definition):
    try:
        _check_budget(value, METADATA_LIMITS)
        validate_document(value, f"{SCHEMA}#/$defs/{definition}")
        encoded = json.dumps(value, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_BYTES:
            raise ValueError("Motion authoring document exceeds 4 MiB")
    except (ValueError, RecursionError) as error:
        raise MotionAuthoringError("MOTION_INPUT_INVALID", str(error)) from error
    return deepcopy(value)


def _encoded(value):
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _basis_matches(expected, actual):
    for name, reference in expected.items():
        current = actual.get(name)
        if reference is None or current is None:
            if reference != current:
                return False
        elif any(current.get(key) != value for key, value in reference.items()):
            return False
    return True


def _check_item_identities(items, previous, retired):
    ids = [item["itemId"] for item in items]
    labels = [item["label"] for item in items]
    if len(set(ids)) != len(ids) or len(set(labels)) != len(labels):
        raise MotionAuthoringError(
            "MOTION_IDENTITY_AMBIGUOUS", "Item identities and labels must be unique"
        )
    old = {item["itemId"]: item for item in previous}
    for item in items:
        _check_existing_label(item, old, retired)


def _check_existing_label(item, old, retired):
    if item["itemId"] in retired or item["label"] in retired.values():
        raise MotionAuthoringError(
            "MOTION_IDENTITY_AMBIGUOUS", "Retired motion identities cannot be reused"
        )
    if item["itemId"] in old and item["label"] != old[item["itemId"]]["label"]:
        raise MotionAuthoringError(
            "MOTION_IDENTITY_AMBIGUOUS", "Existing motion labels cannot be renumbered"
        )


def _changes(previous, items):
    before = {item["itemId"]: item for item in previous}
    after = {item["itemId"]: item for item in items}
    return [
        {
            "itemId": identity,
            "before": before.get(identity),
            "after": after.get(identity),
        }
        for identity in sorted(before.keys() | after.keys())
        if before.get(identity) != after.get(identity)
    ]


def _recipe_treatment(recipe, selection):
    from .camera import CameraError, make_camera_treatment

    try:
        return make_camera_treatment(
            recipe["preset"],
            target_layer_id=recipe["targetLayerId"],
            source_id=recipe["sourceId"],
            source_sha256=recipe["sourceSha256"],
            geometry=recipe["sourceGeometry"],
            options=selection,
            predecessor=recipe.get("predecessor"),
            target_scale=recipe.get("targetScale"),
            target_center=recipe.get("targetCenter"),
            safe_regions=recipe.get("safeRegions", []),
        )
    except CameraError as error:
        raise MotionAuthoringError("MOTION_CAMERA_INVALID", str(error)) from error


def _camera_concept(item, previous, selection):
    recipe = item["cameraRecipe"]
    if (
        item["treatment"] == "static"
        or len(item.get("componentIds", [])) != 1
        or recipe["targetLayerId"] not in item.get("layerIds", [])
    ):
        raise MotionAuthoringError(
            "MOTION_CAMERA_SCOPE",
            "Camera recipe requires one selected component and its declared source layer",
        )
    known, supplied = previous.get("cameraTreatment"), item.get("cameraTreatment")
    if (
        known is not None
        and recipe == previous.get("cameraRecipe")
        and supplied in (None, known)
    ):
        return deepcopy(known)
    generated = _recipe_treatment(recipe, selection)
    if supplied is not None and supplied != known and supplied != generated:
        raise MotionAuthoringError(
            "MOTION_CAMERA_INVALID",
            "Generated camera treatment differs from its selected recipe",
        )
    return generated


def _camera_concepts(items, previous, selection):
    if not any("cameraRecipe" in item for item in items):
        return items
    known = {item["itemId"]: item for item in previous}
    for item in items:
        if "cameraRecipe" in item:
            item["cameraTreatment"] = _camera_concept(
                item, known.get(item["itemId"], {}), selection
            )
    # Generated treatment/options expansion must remain readable before a run
    # choice is frozen or any immutable proposal is published.
    _validate({"items": items}, "proposalInput")
    return items


def _camera_authoring(items, authoring):
    if "animation" not in authoring:
        return
    components = authoring["animation"].get("components", [])
    _require_camera_selection(items, components)
    for item in items:
        if "cameraTreatment" not in item:
            continue
        matches = [
            component
            for component in components
            if component["componentId"] in item["componentIds"]
        ]
        if (
            len(matches) != 1
            or (matches[0].get("extensions") or {}).get("editingCraft")
            != item["cameraTreatment"]
        ):
            raise MotionAuthoringError(
                "MOTION_CAMERA_SELECTION",
                "Timed authoring must retain the exact selected camera treatment and options",
            )


def _require_camera_selection(items, components):
    selected = _scope_ids(items)["animation"]
    camera = _scope_ids([item for item in items if "cameraTreatment" in item])[
        "animation"
    ]
    for component in components:
        if component["componentId"] not in selected:
            continue
        wrapper = (component.get("extensions") or {}).get("editingCraft") or {}
        if "camera" in wrapper and component["componentId"] not in camera:
            raise MotionAuthoringError(
                "MOTION_CAMERA_SELECTION_REQUIRED",
                "A selected camera recipe is required before adding source-picture motion",
            )


def _scope_ids(items):
    return {
        "bmap": {item.get("cueId", item["itemId"]) for item in items},
        "tracks": {value for item in items for value in item.get("layerIds", [])},
        "animation": {
            value for item in items for value in item.get("componentIds", [])
        },
    }


def _scope_metadata(name, snapshot):
    generated = {
        "basis",
        "cmapBasis",
        "animationBasis",
        "dependencies",
        "cues",
        "components",
        "audioTracks",
        "videoTracks",
    }
    result = {key: value for key, value in snapshot.items() if key not in generated}
    if name == "animation" and result.get("strategyContractVersion") in {
        None,
        "1.0.0",
        "2.0.0",
    }:
        # Reader fencing is enforced by the Animation owner and its index.
        # A contract encoding transition does not alter unchanged components.
        result.pop("strategyContractVersion", None)
    if name == "tracks":
        for collection in ("audioTracks", "videoTracks"):
            result[collection] = {
                key: value
                for key, value in snapshot.get(collection, {}).items()
                if key != "layers"
            }
    return result


def _scope_collection(name, key, items):
    indexed = {item[key]: item for item in items or []}
    if len(indexed) != len(items or []):
        raise MotionAuthoringError(
            "MOTION_SCOPE_CONFLICT",
            f"Duplicate {name} identities cannot define a scope",
        )
    return indexed


def _unchanged_collection(name, key, old, new, allowed):
    before = _scope_collection(name, key, old)
    after = _scope_collection(name, key, new)
    for identity in before.keys() | after.keys():
        if before.get(identity) != after.get(identity) and identity not in allowed:
            raise MotionAuthoringError(
                "MOTION_SCOPE_CONFLICT",
                f"Unselected {name} item would change: {identity}",
            )
    return bool(before.keys() - allowed)


class MotionAuthoringService:
    """Constructor/show are metadata-only; only explicit operations write."""

    def __init__(self, workspace, *, camera_runtime=None):
        self.workspace = workspace
        self.camera_runtime = camera_runtime
        self.root = workspace.raw_dir / "edit/motion"
        if not self.root.resolve().is_relative_to(workspace.raw_dir.resolve()):
            raise MotionAuthoringError(
                "MOTION_PATH_INVALID", "Motion records escape project"
            )

    def _read(self, path):
        target = Path(path).resolve()
        if not target.is_relative_to(self.workspace.raw_dir.resolve()):
            raise MotionAuthoringError(
                "MOTION_PATH_INVALID", "Selected metadata escapes project"
            )
        try:
            with target.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Motion metadata byte budget exceeded")
            value = json.loads(raw)
            _check_budget(value, METADATA_LIMITS)
            return value, raw
        except (OSError, ValueError, RecursionError) as error:
            raise MotionAuthoringError("MOTION_METADATA_INVALID", str(error)) from error

    def _ref(self, path, raw):
        return {
            "path": path.relative_to(self.workspace.raw_dir).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    def _load(self, collection, digest, definition):
        if not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest):
            raise MotionAuthoringError(
                "MOTION_INPUT_INVALID", "Exact document SHA-256 required"
            )
        path = self.root / collection / f"{digest}.json"
        value, raw = self._read(path)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise MotionAuthoringError(
                "MOTION_METADATA_CHANGED", "Immutable motion document changed"
            )
        value = _validate(value, definition)
        if (
            value.get("provider", self.workspace.project["provider"])
            != self.workspace.project["provider"]
            or value.get("videoId", self.workspace.video_id) != self.workspace.video_id
        ):
            raise MotionAuthoringError(
                "MOTION_TARGET_INVALID", "Motion document belongs to another project"
            )
        reference = self._ref(path, raw)
        if definition in {"proposal", "decision"}:
            self._verify_result_operation(value, reference, definition)
        return value, reference

    def _put(self, collection, value, definition):
        value = _validate(value, definition)
        raw = _encoded(value)
        digest = hashlib.sha256(raw).hexdigest()
        path = self.root / collection / f"{digest}.json"
        write_immutable_json(path, value)
        return self._ref(path, raw)

    def _run(self):
        if not self.workspace.pipeline_run_path.exists():
            return None
        document, _ = self._read(self.workspace.pipeline_run_path)
        validate_document(document, "avo.pipeline-run.schema.json")
        return document

    def _heads(self):
        return MotionReviewService(self.workspace).project()["basisHeads"]

    def _check_heads(self, expected):
        if not _basis_matches(expected, self._heads()):
            raise MotionAuthoringError(
                "MOTION_STALE_BASIS",
                "Canonical basis changed; inspect the current plan",
            )

    def _request(self, request, operation):
        definition = {
            "plan-propose": "proposeRequest",
            "plan-select": "selectRequest",
            "plan-apply": "applyRequest",
        }[operation]
        return _validate(request, definition)

    def _operation_path(self, request):
        key = content_hash([request["operation"], request["operationId"]])
        return self.root / "operations" / f"{key}.json"

    def _operation_record(self, operation, operation_id):
        path = self._operation_path(
            {"operation": operation, "operationId": operation_id}
        )
        if not path.exists():
            return None
        known, _ = self._read(path)
        _validate(known, "operationIntent")
        expected = {"operation": operation, "operationId": operation_id}
        if (
            any(known[key] != value for key, value in expected.items())
            or any(known["request"][key] != value for key, value in expected.items())
            or known["requestHash"] != content_hash(known["request"])
        ):
            raise MotionAuthoringError(
                "MOTION_OPERATION_CONFLICT",
                "Operation identity or frozen request changed",
            )
        return known

    def _verify_result_operation(self, value, reference, definition):
        operation = "plan-propose" if definition == "proposal" else "plan-select"
        if definition == "proposal":
            operation = value.get("operation", operation)
        known = self._operation_record(operation, value["operationId"])
        if (
            known is None
            or known["requestHash"] != value["requestHash"]
            or known["resultRef"] != reference
        ):
            raise MotionAuthoringError(
                "MOTION_OPERATION_CONFLICT",
                "Immutable result differs from its actual operation request",
            )

    def _known_operation(self, request):
        known = self._operation_record(request["operation"], request["operationId"])
        if known is None:
            return None
        if known["request"] != request:
            raise MotionAuthoringError(
                "MOTION_OPERATION_CONFLICT",
                "Operation identity already records different inputs",
            )
        definition = (
            "proposal"
            if request["operation"] in {"plan-propose", "camera-propose"}
            else "decision"
        )
        collection = "proposals" if definition == "proposal" else "decisions"
        result, _ = self._load(collection, known["resultRef"]["sha256"], definition)
        if (
            result["requestHash"] != content_hash(request)
            or result["operationId"] != request["operationId"]
        ):
            raise MotionAuthoringError(
                "MOTION_OPERATION_CONFLICT",
                "Recorded result belongs to another request",
            )
        return known["resultRef"]

    def _record_operation(self, request, reference):
        write_immutable_json(
            self._operation_path(request),
            {
                "operation": request["operation"],
                "operationId": request["operationId"],
                "requestHash": content_hash(request),
                "resultRef": reference,
                "request": request,
            },
        )

    def _direction_ref(self):
        from avo.direction.brief import BriefService

        service = BriefService(self.workspace.project_path)
        shown = service.show()
        if not shown.get("selection"):
            return None
        path = service.root / shown["refs"]["selection"]["path"]
        _, raw = self._read(path)
        return self._ref(path, raw)

    def _direction_context(self, frozen):
        selected = self.show()
        proposal = selected.get("proposal") or {}
        if proposal.get("requestId") == frozen["requestId"]:
            return deepcopy(proposal.get("direction"))
        if frozen["directionRef"] is None:
            return None
        if self._direction_ref() != frozen["directionRef"]:
            raise MotionAuthoringError(
                "MOTION_DIRECTION_CHANGED",
                "Frozen direction has changed; select an explicit new request",
            )
        from avo.direction.brief import BriefService

        context = BriefService(self.workspace.project_path).stage_context("motion")[
            "context"
        ]
        _check_budget(context, METADATA_LIMITS)
        if self._direction_ref() != frozen["directionRef"]:
            raise MotionAuthoringError(
                "MOTION_DIRECTION_CHANGED",
                "Selected direction changed while capturing context",
            )
        return deepcopy(context)

    def _freeze(self, request):
        store = PipelineRunStore(self.workspace.pipeline_run_path)
        if not store.path.exists():
            store.initialize(
                run_id=f"craft-{self.workspace.video_id}",
                video_id=self.workspace.video_id,
                provider=self.workspace.project["provider"],
                project_path=self.workspace.project_path,
                command="motion",
            )
        run = store.load()
        previous = (run.get("executionChoices") or {}).get("editingCraft")
        selection = validate_editing_craft_selection(request["selection"])
        request_id = request.get("requestId")
        if previous and not request.get("newRequest") and request_id is None:
            return previous
        if request_id is None:
            request_id = "craft-" + content_hash(request["operationId"])[:24]
        run = store.bind_editing_craft_selection(
            selection,
            request_id=request_id,
            new_request=request.get("newRequest", False),
            direction_ref=self._direction_ref(),
            basis_heads={
                name: None
                if value is None
                else {"revisionId": value["revisionId"], "sha256": value["sha256"]}
                for name, value in request["expectedBasis"].items()
            },
            actor=request["actor"],
            reason=request["reason"],
        )
        return run["executionChoices"]["editingCraft"]

    def _proposal_selection(self, request):
        store = PipelineRunStore(self.workspace.pipeline_run_path)
        if (
            store.path.exists()
            and not request.get("newRequest")
            and request.get("requestId") is None
        ):
            previous = (store.load().get("executionChoices") or {}).get("editingCraft")
            if previous:
                return previous["selection"]
        return request["selection"]

    def _items(self, proposal, *, selection):
        items = deepcopy(proposal["items"])
        _check_item_identities(items, [], {})
        previous, retired = [], {}
        if proposal.get("predecessor"):
            old, _ = self._load("proposals", proposal["predecessor"], "proposal")
            previous, retired = old["items"], deepcopy(old["retiredLabels"])
        ids = {item["itemId"] for item in items}
        retired.update(
            {
                item["itemId"]: item["label"]
                for item in previous
                if item["itemId"] not in ids
            }
        )
        _check_item_identities(items, previous, retired)
        items = _camera_concepts(items, previous, selection)
        return items, retired, _changes(previous, items)

    def _proposal_result(self, digest):
        proposal, reference = self._load("proposals", digest, "proposal")
        previous = []
        if proposal["predecessor"]:
            previous = self._load("proposals", proposal["predecessor"], "proposal")[0][
                "items"
            ]
        return {
            "contractVersion": "1.0.0",
            "operation": proposal.get("operation", "plan-propose"),
            "status": "proposed",
            "proposal": proposal,
            "proposalRef": reference,
            "changes": _changes(previous, proposal["items"]),
            "advisories": self._advisories(proposal["items"]),
            "warnings": [],
        }

    @staticmethod
    def _advisories(items):
        groups = {}
        for item in items:
            if item["treatment"] != "static":
                groups.setdefault(item["treatment"], []).append(item["itemId"])
        return [
            {
                "code": "motion-repetition",
                "itemIds": identities,
                "message": "Repeated treatments may be intentional; review variation and reading time.",
            }
            for identities in groups.values()
            if len(identities) >= 3
        ]

    def propose(self, request):
        request = self._request(request, "plan-propose")
        with timeline_writer(self.workspace.timeline_dir):
            known = self._known_operation(request)
            if known:
                return self._with_review(self._proposal_result(known["sha256"]))
            self._check_heads(request["expectedBasis"])
            items, retired, changes = self._items(
                request["proposal"], selection=self._proposal_selection(request)
            )
            camera = self._camera_proposal_environment(request, items)
            frozen = self._freeze(request)
            proposal = {
                **camera,
                "contractVersion": "1.0.0",
                "operationId": request["operationId"],
                "requestHash": content_hash(request),
                "provider": self.workspace.project["provider"],
                "videoId": self.workspace.video_id,
                "requestId": frozen["requestId"],
                "options": frozen["selection"],
                "basisHeads": request["expectedBasis"],
                "items": items,
                "predecessor": request["proposal"].get("predecessor"),
                "retiredLabels": retired,
                "directionRef": frozen["directionRef"],
                "direction": self._direction_context(frozen),
            }
            reference = self._put("proposals", proposal, "proposal")
            self._record_operation(request, reference)
            return self._with_review(
                {**self._proposal_result(reference["sha256"]), "changes": changes}
            )

    def _camera_runtime_hash(self):
        from avo.capabilities import default_proof_capability_registry

        implementation = default_proof_capability_registry().resolve(
            "camera-transform-v1", implementation_id="impl-camera-transform"
        )
        if (
            implementation is None
            or implementation.adapter_id != "ffmpeg.camera-transform"
        ):
            raise MotionAuthoringError(
                "MOTION_CAMERA_UNAVAILABLE",
                "Qualified native camera implementation is unavailable",
            )
        if not callable(self.camera_runtime):
            raise MotionAuthoringError(
                "MOTION_CAMERA_UNAVAILABLE",
                "Explicit camera runtime inspection is required",
            )
        try:
            observed = self.camera_runtime()
            if not isinstance(observed, str) or not re.fullmatch(
                "[a-f0-9]{64}", observed
            ):
                raise ValueError(
                    "Camera runtime requires an observed environment SHA-256"
                )
        except (OSError, ValueError, RuntimeError) as error:
            raise MotionAuthoringError(
                "MOTION_CAMERA_UNAVAILABLE", str(error)
            ) from error
        return observed

    def _camera_proposal_environment(self, request, items):
        if request["operation"] != "camera-propose":
            return {}
        options = self._proposal_selection(request)["effective"]["camera"]
        if not options["enabled"] or not any(
            "cameraTreatment" in item for item in items
        ):
            raise MotionAuthoringError(
                "MOTION_CAMERA_SELECTION_REQUIRED",
                "Select enabled camera options and a typed camera recipe",
            )
        return {
            "operation": "camera-propose",
            "cameraEnvironmentHash": self._camera_runtime_hash(),
        }

    def _dispositions(self, proposal, requested):
        ids = {item["itemId"] for item in proposal["items"]}
        supplied = [item["itemId"] for item in requested]
        if len(supplied) != len(set(supplied)) or not set(supplied) <= ids:
            raise MotionAuthoringError(
                "MOTION_IDENTITY_AMBIGUOUS",
                "Disposition must name unique existing items",
            )
        inherited = self._inherited_dispositions(proposal)
        inherited.update({item["itemId"]: deepcopy(item) for item in requested})
        return [inherited[key] for key in sorted(inherited)]

    def _inherited_dispositions(self, proposal):
        shown = self.show()
        if (
            not shown.get("decision")
            or shown["proposal"]["requestId"] != proposal["requestId"]
        ):
            return {}
        old = {item["itemId"]: item for item in shown["proposal"]["items"]}
        new = {item["itemId"]: item for item in proposal["items"]}
        return {
            item["itemId"]: item
            for item in shown["decision"]["dispositions"]
            if item["itemId"] in new and old.get(item["itemId"]) == new[item["itemId"]]
        }

    def _select_run(self, proposal, proposal_ref, decision, decision_ref):
        store = PipelineRunStore(self.workspace.pipeline_run_path)
        run = store.load()
        selector = {
            "proposalRef": proposal_ref,
            "decisionRef": decision_ref,
            "requestId": proposal["requestId"],
        }
        current = (run.get("extensions") or {}).get("motionProposalSelection")
        if current == selector:
            return selector
        if current is not None:
            run.setdefault("extensions", {}).setdefault(
                "motionProposalSelectionHistory", []
            ).append(deepcopy(current))
        run.setdefault("extensions", {})["motionProposalSelection"] = selector
        store._write(run, expected_updated_at=run["updatedAt"])
        return selector

    def select(self, request):
        request = self._request(request, "plan-select")
        with timeline_writer(self.workspace.timeline_dir):
            known = self._known_operation(request)
            self._check_heads(request["expectedBasis"])
            proposal, proposal_ref = self._load(
                "proposals", request["selection"]["proposalHash"], "proposal"
            )
            if known:
                decision, decision_ref = self._load(
                    "decisions", known["sha256"], "decision"
                )
            else:
                decision = {
                    "contractVersion": "1.0.0",
                    "operationId": request["operationId"],
                    "requestHash": content_hash(request),
                    "provider": self.workspace.project["provider"],
                    "videoId": self.workspace.video_id,
                    "requestId": proposal["requestId"],
                    "proposalHash": proposal_ref["sha256"],
                    "dispositions": self._dispositions(
                        proposal, request["selection"]["dispositions"]
                    ),
                    "actor": request["actor"],
                    "reason": request["reason"],
                }
                decision_ref = self._put("decisions", decision, "decision")
                self._record_operation(request, decision_ref)
            selector = self._select_run(proposal, proposal_ref, decision, decision_ref)
            return self._with_review(
                {
                    "contractVersion": "1.0.0",
                    "operation": "plan-select",
                    "status": "selected",
                    "proposal": proposal,
                    "proposalRef": proposal_ref,
                    "decision": decision,
                    "decisionRef": decision_ref,
                    "selectionRef": selector,
                    "warnings": [],
                }
            )

    def _selected(self, request):
        shown = self.show()
        selected = request["selection"]
        if (
            shown.get("proposalRef", {}).get("sha256") != selected["proposalHash"]
            or shown.get("decisionRef", {}).get("sha256") != selected["decisionHash"]
        ):
            raise MotionAuthoringError(
                "MOTION_SELECTION_REQUIRED",
                "Apply requires the exact current selected proposal and decision",
            )
        if not any(
            item["status"] == "selected" for item in shown["decision"]["dispositions"]
        ):
            raise MotionAuthoringError(
                "MOTION_SELECTION_REQUIRED", "No selected motion items to apply"
            )
        return shown

    def _application_path(self, request):
        return (
            self.root
            / "applications"
            / content_hash(request["operationId"])
            / "current.json"
        )

    def _receipt(self, request):
        path = self._application_path(request)
        if not path.exists():
            return None
        reference, _ = self._read(path)
        receipt, ref = self._load("receipts", reference["sha256"], "receipt")
        if receipt["requestHash"] != content_hash(request):
            raise MotionAuthoringError(
                "MOTION_OPERATION_CONFLICT", "Apply identity records different inputs"
            )
        self._verify_receipt_intent(request, receipt)
        return receipt, ref

    @staticmethod
    def _application_evidence(proposal_ref, decision_ref, request_ref):
        return [
            {
                "evidenceId": "motion-proposal:" + proposal_ref["sha256"],
                "kind": "motion-proposal",
                **proposal_ref,
            },
            {
                "evidenceId": "motion-decision:" + decision_ref["sha256"],
                "kind": "motion-decision",
                **decision_ref,
            },
            {
                "evidenceId": "motion-application:" + request_ref["sha256"],
                "kind": "motion-application",
                **request_ref,
            },
        ]

    def _verify_receipt_intent(self, request, receipt):
        saved, reference = self._load(
            "requests", receipt["requestRef"]["sha256"], "applyRequest"
        )
        bound = {
            "operationId": request["operationId"],
            "requestHash": content_hash(request),
            "expectedBasis": request["expectedBasis"],
            "actor": request["actor"],
            "reason": request["reason"],
        }
        if (
            saved != request
            or reference != receipt["requestRef"]
            or any(receipt[key] != value for key, value in bound.items())
            or receipt["proposalRef"]["sha256"] != request["selection"]["proposalHash"]
            or receipt["decisionRef"]["sha256"] != request["selection"]["decisionHash"]
        ):
            raise MotionAuthoringError(
                "MOTION_OPERATION_CONFLICT",
                "Receipt does not bind the actual application request",
            )
        self._camera_receipt_environment(request, receipt)
        expected = self._application_evidence(
            receipt["proposalRef"], receipt["decisionRef"], reference
        )
        for name, body in receipt["prepared"].items():
            self.workspace.store(name)._validate_revision(body)
            if body["inputEvidenceRefs"] != expected:
                raise MotionAuthoringError(
                    "MOTION_RECOVERY_REQUIRED",
                    "Prepared revision does not bind this proposal, decision and request",
                )

    def _save_receipt(self, request, receipt):
        reference = self._put("receipts", receipt, "receipt")
        atomic_write_json(self._application_path(request), reference)
        return reference

    def _scope(self, shown, authoring):
        selected = {
            item["itemId"]
            for item in shown["decision"]["dispositions"]
            if item["status"] == "selected"
        }
        items = [
            item for item in shown["proposal"]["items"] if item["itemId"] in selected
        ]
        _camera_authoring(items, authoring)
        allowed = _scope_ids(items)
        for name, snapshot in authoring.items():
            index = self.workspace.store(name).load_index()
            previous = (
                self.workspace.store(name).revision(index["headRevisionId"])["snapshot"]
                if index["headRevisionId"]
                else {}
            )
            self._unchanged_unselected(name, previous, snapshot, allowed[name])

    @staticmethod
    def _unchanged_unselected(name, previous, snapshot, allowed):
        collections = {
            "bmap": [("cues", "cueId")],
            "tracks": [("audioTracks", "layerId"), ("videoTracks", "layerId")],
            "animation": [("components", "componentId")],
        }
        unselected = False
        for collection, key in collections[name]:
            old = previous.get(collection, {})
            new = snapshot.get(collection, {})
            if name == "tracks":
                old, new = old.get("layers", []), new.get("layers", [])
            remaining = _unchanged_collection(name, key, old, new, allowed)
            unselected = unselected or remaining
        if unselected and _scope_metadata(name, previous) != _scope_metadata(
            name, snapshot
        ):
            raise MotionAuthoringError(
                "MOTION_SCOPE_CONFLICT",
                f"Unselected {name} items would receive changed global settings",
            )

    def _prepare(self, request, shown):
        if self.workspace.authority != "canonical":
            raise MotionAuthoringError(
                "MOTION_BASIS_REQUIRED",
                "Canonical approved cut is required before timed publication",
            )
        _, cmap, _ = BMapService(self.workspace).current_basis()
        CMapService(self.workspace)._verify_raw(cmap["snapshot"])
        authoring = request["authoring"]
        if (
            "bmap" in authoring
            and "animation" in authoring
            and "tracks" not in authoring
        ):
            raise MotionAuthoringError(
                "MOTION_DEPENDENCY_REQUIRED",
                "Changed BMap requires current prepared Tracks before Animation",
            )
        scoped, camera = self._camera_application(request, shown)
        self._scope(scoped, request["authoring"])
        request_ref = self._put("requests", request, "applyRequest")
        evidence = self._application_evidence(
            shown["proposalRef"], shown["decisionRef"], request_ref
        )
        prepared = {}
        for name, owner in OWNERS.items():
            if name not in request["authoring"]:
                continue
            kwargs = {} if name == "bmap" else {"parents": prepared}
            prepared[name] = owner(self.workspace).prepare_authoring(
                request["authoring"][name],
                actor=request["actor"],
                reason=request["reason"],
                evidence=evidence,
                **kwargs,
            )
        return {
            **camera,
            "contractVersion": "1.0.0",
            "operationId": request["operationId"],
            "requestHash": content_hash(request),
            "requestRef": request_ref,
            "state": "staged",
            "proposalRef": shown["proposalRef"],
            "decisionRef": shown["decisionRef"],
            "expectedBasis": request["expectedBasis"],
            "prepared": prepared,
            "committedHeads": {},
            "actor": request["actor"],
            "reason": request["reason"],
        }

    def _camera_application(self, request, shown):
        if request["operation"] != "camera-apply":
            if self._selected_camera_items(shown):
                raise MotionAuthoringError(
                    "MOTION_CAMERA_OPERATION_REQUIRED",
                    "Selected camera treatments require camera-propose and camera-apply",
                )
            return shown, {}
        if "animation" not in request["authoring"]:
            raise MotionAuthoringError(
                "MOTION_CAMERA_SELECTION_REQUIRED",
                "Camera application requires its selected Animation components",
            )
        scoped = self._camera_scope(shown)
        environment = self._camera_runtime_hash()
        if environment != shown["proposal"].get("cameraEnvironmentHash"):
            raise MotionAuthoringError(
                "MOTION_CAMERA_STALE_RUNTIME",
                "Camera proposal requires its exact observed runtime; validate a new proposal",
            )
        return scoped, {"cameraEnvironmentHash": environment}

    @staticmethod
    def _selected_camera_items(shown):
        selected = {
            item["itemId"]
            for item in shown["decision"]["dispositions"]
            if item["status"] == "selected"
        }
        return [
            deepcopy(item)
            for item in shown["proposal"]["items"]
            if item["itemId"] in selected and "cameraTreatment" in item
        ]

    @staticmethod
    def _camera_scope(shown):
        items = MotionAuthoringService._selected_camera_items(shown)
        if not items:
            raise MotionAuthoringError(
                "MOTION_CAMERA_SELECTION_REQUIRED",
                "Select an actual typed camera proposal before application",
            )
        for item in items:
            item["layerIds"] = [item["cameraTreatment"]["camera"]["targetLayerId"]]
        scoped = deepcopy(shown)
        scoped["proposal"]["items"] = items
        return scoped

    @property
    def _pending(self):
        return self.workspace.timeline_dir / "motion-application.pending.json"

    def _guard_pending(self, request):
        other = self.workspace.timeline_dir / "import-activation.pending.json"
        if other.exists() or other.is_symlink():
            raise MotionAuthoringError(
                "MOTION_RECOVERY_REQUIRED", "A pending import requires its own recovery"
            )
        if not self._pending.exists() and not self._pending.is_symlink():
            return
        marker, _ = self._read(self._pending)
        if marker != {
            "operationId": request["operationId"],
            "requestHash": content_hash(request),
        }:
            raise MotionAuthoringError(
                "MOTION_RECOVERY_REQUIRED",
                "Another motion operation requires exact recovery",
            )

    def _actual_committed(self, receipt, *, require_active=True):
        committed = {}
        for name, prepared in receipt["prepared"].items():
            store = self.workspace.store(name)
            index = store.load_index()
            matches = [
                ref
                for ref in index["revisionRefs"]
                if ref["revisionId"] == prepared["revisionId"]
            ]
            if not matches:
                continue
            actual = store.revision(prepared["revisionId"])
            if actual["contentHash"] != prepared["contentSha256"]:
                raise MotionAuthoringError(
                    "MOTION_RECOVERY_REQUIRED",
                    "Prepared revision identity or active head changed",
                )
            if require_active and index["headRevisionId"] != prepared["revisionId"]:
                raise MotionAuthoringError(
                    "MOTION_RECOVERY_REQUIRED", "Prepared active head changed"
                )
            committed[name] = {
                "revisionId": prepared["revisionId"],
                "sha256": prepared["contentSha256"],
            }
        return committed

    def _apply_owners(self, request, receipt):
        receipt["committedHeads"] = self._actual_committed(receipt)
        for name, owner in OWNERS.items():
            if name not in receipt["prepared"]:
                continue
            prepared = receipt["prepared"][name]
            if name in receipt["committedHeads"]:
                continue
            original = request["expectedBasis"][name]
            expected = None if original is None else original["sha256"]
            if self.workspace.store(name).head_hash() != expected:
                raise MotionAuthoringError(
                    "MOTION_STALE_BASIS", "Uncommitted target changed during recovery"
                )
            owner(self.workspace).author(
                request["authoring"][name],
                actor=request["actor"],
                reason=request["reason"],
                prepared=prepared,
            )
            receipt["committedHeads"] = self._actual_committed(receipt)
            self._save_receipt(request, receipt)

    def _verify_recovery_inputs(self, request, receipt):
        self._camera_recovery(request, receipt)
        _, cmap, _ = BMapService(self.workspace).current_basis()
        CMapService(self.workspace)._verify_raw(cmap["snapshot"])
        for name, owner in OWNERS.items():
            if name not in receipt["prepared"]:
                continue
            kwargs = {} if name == "bmap" else {"parents": receipt["prepared"]}
            fresh = owner(self.workspace).prepare_authoring(
                request["authoring"][name],
                actor=request["actor"],
                reason=request["reason"],
                evidence=receipt["prepared"][name]["inputEvidenceRefs"],
                **kwargs,
            )
            original = receipt["prepared"][name]
            if (
                fresh["snapshot"] != original["snapshot"]
                or fresh["basis"] != original["basis"]
            ):
                raise MotionAuthoringError(
                    "MOTION_STALE_BASIS",
                    "Prepared publication source/basis changed during recovery",
                )

    def _camera_receipt_environment(self, request, receipt):
        if request["operation"] != "camera-apply":
            return None
        proposal, _ = self._load(
            "proposals", receipt["proposalRef"]["sha256"], "proposal"
        )
        expected = proposal.get("cameraEnvironmentHash")
        if expected is None or receipt.get("cameraEnvironmentHash") != expected:
            raise MotionAuthoringError(
                "MOTION_RECOVERY_REQUIRED",
                "Camera receipt differs from its selected proposal environment",
            )
        return expected

    def _camera_recovery(self, request, receipt):
        expected = self._camera_receipt_environment(request, receipt)
        if (
            expected is not None
            and receipt["state"] != "committed"
            and self._camera_runtime_hash() != expected
        ):
            raise MotionAuthoringError(
                "MOTION_RECOVERY_REQUIRED",
                "Camera runtime changed during interrupted publication",
            )

    def _finish(self, request, receipt, shown):
        receipt["state"] = "committed"
        reference = self._save_receipt(request, receipt)
        store = PipelineRunStore(self.workspace.pipeline_run_path)
        run = store.load()
        selector = run["extensions"]["motionProposalSelection"]
        selector["receiptRef"] = reference
        store._write(run, expected_updated_at=run["updatedAt"])
        self._pending.unlink(missing_ok=True)
        return self._with_review(
            {
                **shown,
                "operation": request["operation"],
                "status": "committed",
                "receipt": receipt,
                "receiptRef": reference,
                "committedHeads": receipt["committedHeads"],
            }
        )

    def apply(self, request):
        request = self._request(request, "plan-apply")
        with timeline_writer(self.workspace.timeline_dir, recovery=True):
            self._guard_pending(request)
            marker = {
                "operationId": request["operationId"],
                "requestHash": content_hash(request),
            }
            with motion_application_access(self.workspace.timeline_dir, marker):
                return self._apply_locked(request)

    def _apply_locked(self, request):
        known = self._receipt(request)
        shown = self._selected(request)
        if known and known[0]["state"] == "committed":
            self._verify_committed_receipt(known[0])
            if self._pending.exists():
                self._verify_recovery_inputs(request, known[0])
                return self._finish(request, known[0], shown)
            return self._with_review(
                {
                    **shown,
                    "operation": request["operation"],
                    "status": "committed",
                    "receipt": known[0],
                    "receiptRef": known[1],
                    "committedHeads": known[0]["committedHeads"],
                }
            )
        if known:
            receipt = known[0]
            try:
                self._verify_recovery_inputs(request, receipt)
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                raise MotionAuthoringError(
                    "MOTION_RECOVERY_REQUIRED", str(error)
                ) from error
        else:
            self._check_heads(request["expectedBasis"])
            try:
                receipt = self._prepare(request, shown)
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                raise MotionAuthoringError(
                    "MOTION_PREFLIGHT_FAILED", str(error)
                ) from error
            reference = self._save_receipt(request, receipt)
            self._record_operation(request, reference)
        return self._commit(request, receipt, shown)

    def _commit(self, request, receipt, shown):
        try:
            atomic_write_json(
                self._pending,
                {
                    "operationId": request["operationId"],
                    "requestHash": content_hash(request),
                },
            )
            receipt["state"] = "committing"
            self._save_receipt(request, receipt)
            with fingerprint_stage(verify_on_exit=True):
                self._verify_recovery_inputs(request, receipt)
                self._apply_owners(request, receipt)
            return self._finish(request, receipt, shown)
        except Exception as error:
            receipt["state"] = "recovery-needed"
            try:
                self._save_receipt(request, receipt)
            except (OSError, ValueError, RuntimeError):
                pass  # The durable pending marker still blocks unrelated mutations.
            raise MotionAuthoringError(
                "MOTION_RECOVERY_REQUIRED", str(error)
            ) from error

    def _show_selected(self, selector, proposal_hash):
        reference = selector["proposalRef"]
        digest = proposal_hash or reference["sha256"]
        result = self._proposal_result(digest)
        if digest != reference["sha256"]:
            return result
        if reference != result["proposalRef"]:
            raise MotionAuthoringError(
                "MOTION_METADATA_CHANGED",
                "Selected proposal reference differs from contained metadata",
            )
        decision, decision_ref = self._selected_decision(selector, digest)
        expected, applied = self._receipt_basis(result, selector)
        stale = (
            not _basis_matches(expected, self._heads())
            or result["proposal"]["directionRef"] != self._direction_ref()
        )
        return {
            **result,
            "status": "stale" if stale else "selected",
            "decision": decision,
            "decisionRef": decision_ref,
            "selectionRef": deepcopy(selector),
            "applied": applied,
            "warnings": ["Selected proposal basis changed"] if stale else [],
        }

    def _selected_decision(self, selector, digest):
        decision, reference = self._load(
            "decisions", selector["decisionRef"]["sha256"], "decision"
        )
        if (
            reference != selector["decisionRef"]
            or decision["proposalHash"] != digest
            or decision["requestId"] != selector["requestId"]
        ):
            raise MotionAuthoringError(
                "MOTION_SELECTION_REQUIRED",
                "Selected proposal/decision/request identities differ",
            )
        return decision, reference

    def _receipt_basis(self, result, selector):
        expected = deepcopy(result["proposal"]["basisHeads"])
        if not selector.get("receiptRef"):
            return expected, False
        receipt, reference = self._load(
            "receipts", selector["receiptRef"]["sha256"], "receipt"
        )
        if (
            reference != selector["receiptRef"]
            or receipt["proposalRef"] != result["proposalRef"]
            or receipt["decisionRef"] != selector["decisionRef"]
        ):
            raise MotionAuthoringError(
                "MOTION_METADATA_CHANGED",
                "Selected receipt differs from this proposal/decision",
            )
        self._verify_committed_receipt(receipt)
        expected.update(receipt["committedHeads"])
        return expected, receipt["state"] == "committed"

    def _verify_committed_receipt(self, receipt):
        request, _ = self._load(
            "requests", receipt["requestRef"]["sha256"], "applyRequest"
        )
        self._verify_receipt_intent(request, receipt)
        actual = self._actual_committed(receipt, require_active=False)
        if (
            set(actual) != set(receipt["prepared"])
            or actual != receipt["committedHeads"]
        ):
            raise MotionAuthoringError(
                "MOTION_RECOVERY_REQUIRED",
                "Receipt claims canonical revisions that were not published",
            )

    def show(self, proposal_hash=None):
        run = self._run()
        selector = ((run or {}).get("extensions") or {}).get("motionProposalSelection")
        if selector is None:
            return (
                self._proposal_result(proposal_hash)
                if proposal_hash
                else {
                    "contractVersion": "1.0.0",
                    "operation": "plan-show",
                    "status": "unselected",
                    "proposal": None,
                    "warnings": [],
                }
            )
        _validate(selector, "selectionRef")
        return self._show_selected(selector, proposal_hash)

    @staticmethod
    def review_context(shown):
        proposal = deepcopy(shown.get("proposal") or {})
        choices = {
            item["itemId"]: item["status"]
            for item in (shown.get("decision") or {}).get("dispositions", [])
        }
        for item in proposal.get("items", []):
            state = choices.get(item["itemId"], "proposed")
            item["disposition"] = (
                "applied"
                if state == "selected"
                and (shown["status"] == "committed" or shown.get("applied"))
                else state
            )
        return {
            "proposal": proposal,
            "options": proposal.get("options", {}),
            "advisories": MotionAuthoringService._advisories(proposal.get("items", [])),
            "direction": deepcopy(
                proposal.get("direction") or {"reference": proposal.get("directionRef")}
            ),
        }

    def _with_review(self, result):
        try:
            service = MotionReviewService(self.workspace)
            snapshot = service.project(self.review_context(result))
            result["review"] = service.publish(
                snapshot, expected_basis=snapshot["basisHeads"]
            )
            result["reviewReady"] = result["review"].get("status") == "published"
        except (OSError, ValueError, RuntimeError) as error:
            result.setdefault("warnings", []).append(
                f"Current motion presentation unavailable: {error}"
            )
            result["reviewReady"] = False
        return result
