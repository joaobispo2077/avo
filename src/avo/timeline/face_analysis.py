"""Publish an explicit face observation against the current original source."""

import hashlib
from fractions import Fraction
from pathlib import Path

from avo.editing_craft import validate_editing_craft_selection
from avo.reference_analysis import SCHEMA, freeze_face_trajectory

from .contracts import content_hash, file_fingerprint, validate_document
from .motion_authoring import MotionAuthoringService
from .store import timeline_writer, write_immutable_json

ANALYSIS_PARAMETERS = ("sourceRange", "seed", "minimumOverlap", "maximumGapTicks")


def _check_original_binding(source, request):
    if source["fingerprint"]["sha256"] != request["sourceSha256"]:
        raise ValueError("Face analysis differs from the current original source")
    declared = (source.get("streamMetadata") or {}).get("videoStreamIndex")
    if declared is not None and declared != request["streamIndex"]:
        raise ValueError("Face analysis differs from the current original video stream")


def _current_source(workspace, request):
    index = workspace.require_active("cmap")
    cmap = workspace.store("cmap").revision(index["headRevisionId"])["snapshot"]
    matches = [
        item for item in cmap["sources"] if item["sourceId"] == request["sourceId"]
    ]
    if len(matches) != 1:
        raise ValueError("Face analysis requires one current original source")
    (source,) = matches
    _check_original_binding(source, request)
    identity = source["fingerprint"]
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
    actual = observed["request"]
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
    trajectory = freeze_face_trajectory(observed)
    _require_observed_scope(observed, request, identity)
    record = {
        "request": request,
        "observation": observed,
        "trajectory": trajectory,
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
        "trajectoryHash": trajectory["trajectoryHash"],
        "uncertainIntervals": trajectory["uncertainIntervals"],
        "review": "required",
    }


def validate_face_record(workspace, binding, record, digest):
    """Validate selected evidence, including when retained from an older revision."""
    validate_document(binding, SCHEMA + "#/$defs/faceAnchor")
    reference = binding["observationRef"]
    if (
        digest != reference["sha256"]
        or content_hash(record) != Path(reference["locator"]).stem
    ):
        raise ValueError("Frozen face observation bytes changed")
    if (
        record.get("videoId") != workspace.video_id
        or record.get("provider") != workspace.project["provider"]
    ):
        raise ValueError("Frozen face observation belongs to another video")
    request = record.get("request")
    validate_document(request, SCHEMA + "#/$defs/faceAnalyzeRequest")
    observation = record.get("observation")
    trajectory = freeze_face_trajectory(observation)
    source = trajectory["source"]
    if (source["sourceId"], source["sha256"]) != (
        request["sourceId"],
        request["sourceSha256"],
    ):
        raise ValueError("Face observation differs from its selected original source")
    _require_observed_scope(observation, request, source)
    if (
        record.get("trajectory") != trajectory
        or binding["trajectoryHash"] != trajectory["trajectoryHash"]
    ):
        raise ValueError("Frozen face trajectory changed or needs a new face analysis")
    return trajectory


def read_face_anchor(workspace, binding):
    """Resolve exact prepared evidence without decoding video or loading a model."""
    validate_document(binding, SCHEMA + "#/$defs/faceAnchor")
    reference = binding["observationRef"]
    path = workspace.raw_dir / reference["locator"]
    record, raw = MotionAuthoringService(workspace)._read(path)
    trajectory = validate_face_record(
        workspace, binding, record, hashlib.sha256(raw).hexdigest()
    )
    request = record["request"]
    _, source = _current_source(workspace, request)
    if trajectory["source"] != source:
        raise ValueError(
            "Frozen face trajectory differs from the current source fingerprint"
        )
    if trajectory["streamOriginTicks"] is None:
        raise ValueError(
            "Frozen face trajectory requires a verified source stream origin"
        )
    return trajectory, request["streamIndex"]


def read_face_treatment(workspace, treatment):
    trajectory, stream = read_face_anchor(workspace, treatment["faceAnchor"])
    geometry = treatment["sourceGeometry"]
    measured = trajectory["geometry"]
    if (measured["width"], measured["height"], measured["rotation"]) != (
        geometry["codedWidth"],
        geometry["codedHeight"],
        geometry["rotationDegrees"] % 360,
    ) or _ratio(measured["sampleAspectRatio"]) != _ratio(geometry["sampleAspectRatio"]):
        raise ValueError(
            "Face trajectory display geometry differs from the selected camera"
        )
    source = trajectory["source"]
    if (source["sourceId"], source["sha256"]) != (
        treatment["camera"].get("sourceId"),
        treatment["sourceSha256"],
    ):
        raise ValueError("Face trajectory source differs from the selected camera")
    return trajectory, stream


def _ratio(value):
    return Fraction(value["num"], value["den"])


def _face_pin_present(workspace):
    from avo.model_sources import resolve_job

    job = resolve_job(
        "face_detect", project=workspace.project, video_key=workspace.video_id
    )
    source = job.pin.get("source") or {}
    runtime = job.pin.get("runtime") or {}
    paths = (source.get("artifactPath"), runtime.get("pythonEnv"))
    return source.get("kind") == "artifact" and all(
        path and Path(path).is_file() for path in paths
    )


def describe_face_readiness(workspace, treatment, options):
    """Describe opt-in preparation from local metadata; never invoke the detector."""
    binding = (treatment or {}).get("faceAnchor")
    if binding is None:
        try:
            available = _face_pin_present(workspace)
        except (OSError, ValueError, TypeError):
            available = False
        if not available:
            return {
                "status": "capability-unavailable",
                "next": "Prepare a pinned local face model and isolated CPU runtime.",
            }
        return {
            "status": "subject-selection-required",
            "next": "Choose the original source range and a sampled face, then run face analysis.",
        }
    try:
        trajectory, _ = read_face_treatment(workspace, treatment)
    except (ValueError, OSError, KeyError, TypeError) as error:
        return {"status": "observation-unavailable", "next": str(error)[:500]}
    uncertainty = trajectory["uncertainIntervals"]
    fallback = options["onLost"]
    status = "measured"
    if uncertainty:
        reviewed = fallback in {"hold", "static"} and "fallbackReview" in binding
        status = "fallback-recorded" if reviewed else "fallback-review-required"
    return {
        "status": status,
        "trajectoryHash": trajectory["trajectoryHash"],
        "sourceRange": trajectory["sourceRange"],
        "uncertainIntervals": uncertainty,
        "onLost": fallback,
    }


__all__ = [
    "analyze_face",
    "read_face_anchor",
    "read_face_treatment",
    "validate_face_record",
]
