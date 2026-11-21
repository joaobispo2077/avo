"""Canonical placement and exact native receipts for generated static cards."""

from fractions import Fraction
from pathlib import Path

from avo.artcraft import read_authoring_export

from .artcraft_binding import require_artcraft_media_scope
from .contracts import content_hash, file_fingerprint, validate_document
from .media_admission import FORBIDDEN_OUTPUT_CLASSES

_REF = "avo.artcraft.schema.json#/$defs/exportRef"
_PARAMETERS = "avo.proof-plan.schema.json#/$defs/generatedStillParameters"


def is_generated_still(operation):
    return "generatedStillRef" in (operation.get("parameters") or {})


def read_generated_still(reference):
    validate_document(reference, _REF)
    expected = reference["job"]
    path = Path(expected["locator"])
    if (
        not path.is_absolute()
        or path.resolve() != path
        or file_fingerprint(path) != expected
    ):
        raise ValueError("Generated still job receipt changed or uses an alias")
    job, event = read_authoring_export(path, expected_head=reference["exportHead"])
    profile = job["output"]["role"], job["output"]["format"], job["observation"]["app"]
    if (
        profile != ("generated-still", "png", "vectorcraft")
        or "stillEvidence" not in event
    ):
        raise ValueError("Generated still requires a verified VectorCraft card")
    if job["inputs"]:
        raise ValueError(
            "Generated VectorCraft card has unsupported external dependencies"
        )
    if FORBIDDEN_OUTPUT_CLASSES.intersection(
        part.casefold() for part in Path(event["outputs"][0]["locator"]).parts
    ):
        raise ValueError("Generated still has prohibited proof ancestry")
    return job, event


def require_generated_still_layer(layer, *, workspace=None):
    if (
        layer.get("role") != "overlay"
        or "source" not in layer
        or "placement" not in layer
        or "generatedSourceRef" in layer
    ):
        raise ValueError(
            "Generated still needs its own static overlay layer and placement"
        )
    job, event = read_generated_still(layer["generatedStillRef"])
    if layer["source"] != event["outputs"][0]:
        raise ValueError("Tracks generated still differs from its verified PNG")
    _require_intrinsic_geometry(layer["placement"], event["stillEvidence"])
    if workspace is not None:
        require_artcraft_media_scope(workspace, job, "Generated still")


def _require_intrinsic_geometry(placement, evidence):
    if any(placement[key] != evidence[key] for key in ("width", "height")):
        raise ValueError("Generated still placement differs from its intrinsic canvas")


def _require_static_operation(operation):
    if operation["kind"] != "overlay-image":
        raise ValueError("Generated still requires the static overlay-image operation")
    params = operation["parameters"]
    validate_document(params, _PARAMETERS)
    expected = ["program-picture", "generated-still:" + operation["operationId"]]
    if operation["inputs"] != expected:
        raise ValueError(
            "Generated still operation does not consume its exact still input"
        )
    job, event = read_generated_still(params["generatedStillRef"])
    if params["sourceFingerprint"] != event["outputs"][0]:
        raise ValueError("Generated still fingerprint differs from the verified PNG")
    _require_intrinsic_geometry(params["placement"], event["stillEvidence"])
    return job, event


def _placement_range(region, rate):
    clock = region.get("timebase") or {"num": rate["den"], "den": rate["num"]}
    scale = Fraction(clock["num"] * rate["num"], clock["den"] * rate["den"])
    start, end = (scale * region[key] for key in ("startTicks", "endTicks"))
    if start.denominator != 1 or end.denominator != 1 or not 0 <= start < end:
        raise ValueError("Generated still placement must align to exact program frames")
    return {"startFrame": int(start), "endFrameExclusive": int(end)}


def _match_still_layer(operation, layer, rate):
    params = operation["parameters"]
    if any(
        layer.get(left) != params[right]
        for left, right in (
            ("generatedStillRef", "generatedStillRef"),
            ("source", "sourceFingerprint"),
            ("placement", "placement"),
            ("zOrder", "zOrder"),
            ("role", "layerRole"),
        )
    ):
        raise ValueError(
            "Generated still operation differs from its canonical Tracks layer"
        )
    candidates = [_placement_range(item, rate) for item in layer["regions"]]
    if candidates.count(operation["outputRange"]) != 1:
        raise ValueError(
            "Generated still operation has no exact unique canonical frame range"
        )


def generated_still_locks(workspace, graph, output, *, checkpoint=None):
    operations = [
        item for item in graph.get("operations", []) if is_generated_still(item)
    ]
    if not operations:
        return {}
    if checkpoint == "cut-proof":
        raise ValueError("Cut proof cannot include generated stills")
    store = workspace.store("tracks")
    revision = store.revision(workspace.require_active("tracks")["headRevisionId"])
    layers = {
        item["layerId"]: item
        for item in revision["snapshot"].get("videoTracks", {}).get("layers", [])
    }
    locks, occupied = {}, set()
    for operation in operations:
        job, _ = _require_static_operation(operation)
        require_artcraft_media_scope(workspace, job, "Generated still")
        layer = layers[operation["parameters"]["layerId"]]
        _match_still_layer(operation, layer, output["frameRate"])
        identity = (layer["layerId"], content_hash(operation["outputRange"]))
        if identity in occupied:
            raise ValueError("Duplicate generated still Tracks placement")
        occupied.add(identity)
        locks["generated-still:" + operation["operationId"]] = content_hash(operation)
    return locks


def resolve_generated_still_operation(operation, lock):
    key = "generated-still:" + operation["operationId"]
    if lock.get(key) != content_hash(operation):
        raise ValueError("Generated still operation lacks its exact proof binding")
    return _require_static_operation(operation)
