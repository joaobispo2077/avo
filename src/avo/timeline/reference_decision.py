"""Create project-only direction descriptors from inspected reference records."""

import hashlib
import json

from avo.reference_analysis import SCHEMA

from .contracts import content_hash, file_fingerprint, validate_document
from .motion_authoring import MotionAuthoringService
from .reference_observation import _path
from .store import timeline_writer, write_immutable_json

MAX_INSPECTION_BYTES = 16 * 1024 * 1024
METRICS = {
    "global-motion": "global",
    "element-motion": "residual",
    "scene-changes": "cutCandidate",
    "brightness": "brightness",
}


def _inspection(workspace, reference):
    path = _path(workspace, reference["locator"])
    with path.open("rb") as stream:
        raw = stream.read(MAX_INSPECTION_BYTES + 1)
    if (
        len(raw) > MAX_INSPECTION_BYTES
        or hashlib.sha256(raw).hexdigest() != reference["sha256"]
    ):
        raise ValueError(
            "Reference inspection bytes changed or exceed the review budget"
        )
    record = json.loads(raw)
    if not isinstance(record, dict) or content_hash(record) != path.stem:
        raise ValueError("Reference inspection identity changed")
    if (record.get("provider"), record.get("videoId"), record.get("use")) != (
        workspace.project["provider"],
        workspace.video_id,
        "inspection-only",
    ):
        raise ValueError("Reference inspection belongs to another project")
    return record


def _selected_clip(record, clip_id):
    matching = [row for row in record["clips"] if row["clipId"] == clip_id]
    if len(matching) != 1:
        raise ValueError("Reference review requires one exact inspected clip")
    observation = matching[0]["observation"]
    validate_document(observation, SCHEMA + "#/$defs/referenceObservation")
    return observation


def _global_summary(rows):
    x = max(abs(row["translateX"]) for row in rows)
    y = max(abs(row["translateY"]) for row in rows)
    return f"Maximum estimated frame-center travel between samples was {x:.1%} of width and {y:.1%} of height."


def _brightness_summary(rows):
    levels = [level for row in rows for level in (row["before"], row["after"])]
    return (
        f"Recorded mean grayscale ranged from {min(levels):.1%} to {max(levels):.1%}."
    )


def _timing_summary(interpretation):
    rows = interpretation.get("timingCandidates", [])
    holds = sum(row["kind"] == "hold" for row in rows)
    return f"The sampled frames support {holds} candidate holds and {len(rows) - holds} candidate reveals."


def _easing_summary(interpretation):
    result = interpretation["easing"]
    return f"Approximate {result['curve']} fit on {result['axis']} between ticks {result['startTicks']}–{result['endTicks']} (normalized progress RMSE {result['progressRmse']:.3f})."


def _audio_summary(interpretation):
    audio = interpretation["audioTiming"]
    words = sum(
        row["status"] == "observed" for row in interpretation.get("wordTiming", [])
    )
    overlaps = len(interpretation["audioRevealRelationships"])
    return f"Observed {len(audio['onsetSamples'])} energy onset candidates at {audio['sampleRate']} Hz, with possible overlap in {overlaps} reveal windows. Bound {words} prepared word starts to this audio clock."


def _interpreted_summary(observation, aspect):
    details = observation["interpretation"]
    available = details["availableEvidence"]
    if aspect == "hold-reveal" and available.get(aspect) == "measured-candidates":
        return _timing_summary(details)
    if aspect == "easing" and isinstance(details["easing"], dict):
        return _easing_summary(details)
    if aspect == "audio-word-timing" and available.get(aspect) == "audio-candidates":
        return _audio_summary(details)
    raise ValueError(f"Selected reference aspect has no measured coverage: {aspect}")


def _measurements_summary(observation, aspects):
    scope = observation["request"]["sourceRange"]
    clock = scope["timebase"]
    intervals = observation["intervals"]
    details = [
        (
            f"Inspected {len(intervals)} sampled intervals in native source ticks {scope['startTicks']}–{scope['endTicks']}. "
            f"Each tick is {clock['num']}/{clock['den']} seconds."
        )
    ]
    summaries = {
        "global-motion": _global_summary,
        "element-motion": lambda rows: (
            f"Residual motion was measured in {len(rows)} intervals."
        ),
        "scene-changes": lambda rows: (
            f"Detected {sum(rows)} candidate scene changes between samples."
        ),
        "brightness": _brightness_summary,
    }
    for aspect in aspects:
        metric = METRICS.get(aspect)
        if metric is None:
            details.append(_interpreted_summary(observation, aspect))
            continue
        rows = [interval[metric] for interval in intervals if metric in interval]
        if not rows:
            raise ValueError(
                f"Selected reference aspect has no measured coverage: {aspect}"
            )
        details.append(summaries[aspect](rows))
    return " ".join(details)


def _descriptor(workspace, request, observation):
    reference = request["observationRef"]
    if "easing" in request["selectedAspects"] and request["disposition"] != "qualify":
        raise ValueError("Approximate easing requires a qualified reference decision")
    result = {
        "schemaVersion": "1.0.0",
        "referenceId": "measured-reference-" + content_hash(request)[:24],
        "label": request["clipId"],
        "locator": None,
        "selectedAspects": request["selectedAspects"],
        "description": _measurements_summary(observation, request["selectedAspects"]),
        "observationKind": "frozen-inspection",
        "applicability": ["current project direction"],
        "exclusions": ["media admission", "provider promotion", "creator approval"],
        "knownUsageLimits": request.get(
            "qualification",
            "Use the inspected measurements as project planning evidence.",
        ),
        "inspectionRef": {
            "id": observation["analysisHash"],
            "documentHash": reference["sha256"],
            "path": reference["locator"],
        },
        "projectScope": {
            "provider": workspace.project["provider"],
            "videoId": str(workspace.project.get("videoId") or workspace.raw_dir.name),
        },
    }
    validate_document(result, "avo.briefstart.schema.json#/$defs/ReferenceDescriptor")
    return result


def _write_reference(workspace, value, category):
    name = f"edit/motion/references/{category}/{content_hash(value)}.json"
    path = write_immutable_json(_path(workspace, name), value)
    return {"locator": name, "sha256": file_fingerprint(path)["sha256"]}


def decide_reference(workspace, request):
    validate_document(request, SCHEMA + "#/$defs/referenceDecisionRequest")
    authoring = MotionAuthoringService(workspace)
    with timeline_writer(workspace.timeline_dir):
        authoring._check_heads(request["expectedBasis"])
        record = _inspection(workspace, request["observationRef"])
        observation = _selected_clip(record, request["clipId"])
        positive = request["disposition"] != "reject"
        descriptor = _descriptor(workspace, request, observation) if positive else None
        result = {
            "request": request,
            "provider": workspace.project["provider"],
            "videoId": workspace.video_id,
            "scope": "project-only",
            "disposition": request["disposition"],
            "descriptorRef": _write_reference(workspace, descriptor, "descriptors")
            if positive
            else None,
        }
        decision = _write_reference(workspace, result, "decisions")
    return {"status": "recorded", "decisionRef": decision, **result}
