"""Publish an explicit face observation against the current original source."""

from pathlib import Path

from avo.editing_craft import validate_editing_craft_selection
from avo.reference_analysis import SCHEMA

from .contracts import content_hash, file_fingerprint, validate_document
from .motion_authoring import MotionAuthoringService
from .store import timeline_writer, write_immutable_json

ANALYSIS_PARAMETERS = ("sourceRange", "seed", "minimumOverlap", "maximumGapTicks")


def _current_source(workspace, request):
    index = workspace.require_active("cmap")
    cmap = workspace.store("cmap").revision(index["headRevisionId"])["snapshot"]
    matches = [
        item for item in cmap["sources"] if item["sourceId"] == request["sourceId"]
    ]
    if len(matches) != 1:
        raise ValueError("Face analysis requires one current original source")
    (source,) = matches
    identity = source["fingerprint"]
    if identity["sha256"] != request["sourceSha256"]:
        raise ValueError("Face analysis differs from the current original source")
    locator = source.get("locator") or identity.get("locator")
    if not locator or not Path(locator).is_absolute():
        raise ValueError("The current original requires an absolute local path")
    path = Path(locator).resolve()
    if path.is_relative_to((workspace.raw_dir / "edit").resolve()):
        raise ValueError("Derived edit media cannot supply a face observation")
    return path, {
        "sourceId": request["sourceId"],
        "sha256": identity["sha256"],
        "sizeBytes": identity["sizeBytes"],
    }


def _require_observed_scope(observed, request, source):
    validate_document(observed, SCHEMA + "#/$defs/faceObservation")
    payload = {key: value for key, value in observed.items() if key != "analysisHash"}
    actual = observed["request"]
    if observed["analysisHash"] != content_hash(payload):
        raise ValueError("Face observation identity changed")
    if actual["source"] != source or any(
        actual[key] != request[key] for key in ANALYSIS_PARAMETERS
    ):
        raise ValueError(
            "Face observations differ from the selected source or analysis parameters"
        )


def analyze_face(workspace, request, analyze):
    """Measure through the injected adapter and save only the observed facts."""
    validate_document(request, SCHEMA + "#/$defs/faceAnalyzeRequest")
    selection = validate_editing_craft_selection(request["selection"])["effective"]
    camera = selection["camera"]
    if not camera["enabled"] or camera["faceAnchor"] != "selected-subject":
        raise ValueError("Face analysis requires explicitly selected face anchoring")
    authoring = MotionAuthoringService(workspace)
    authoring._check_heads(request["expectedBasis"])
    source, identity = _current_source(workspace, request)
    observed = analyze(source, request)
    _require_observed_scope(observed, request, identity)
    record = {
        "request": request,
        "observation": observed,
        "videoId": workspace.video_id,
        "provider": workspace.project["provider"],
    }
    name = "edit/motion/face/" + content_hash(record) + ".json"
    path = workspace.raw_dir / name
    with timeline_writer(workspace.timeline_dir):
        authoring._check_heads(request["expectedBasis"])
        final = file_fingerprint(source)
        if any(final[key] != identity[key] for key in ("sha256", "sizeBytes")):
            raise ValueError("Original source bytes changed during face analysis")
        if not path.resolve().is_relative_to(workspace.raw_dir.resolve()):
            raise ValueError("Face observation path escapes the project")
        write_immutable_json(path, record)
        digest = file_fingerprint(path)["sha256"]
    return {
        "status": "observed",
        "observationRef": {"locator": name, "sha256": digest},
        "coverage": observed["coverage"],
        "review": "required",
    }


__all__ = ["analyze_face"]
