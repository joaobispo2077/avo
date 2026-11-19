"""Resolve selected sound anchors from canonical metadata, without execution."""

from fractions import Fraction

from .camera import _behavior, _encoded
from .contracts import content_hash, validate_document
from .mapping import _time, cmap_output_timebase, cmap_raw_to_output
from .motion_metadata import METADATA_LIMITS, _check_budget
from .sound_fitting import SoundPlanningError


def _source_record(anchor, cmap):
    matches = [
        source
        for source in cmap.get("sources", [])
        if source["sourceId"] == anchor["sourceId"]
    ]
    if len(matches) != 1:
        raise SoundPlanningError("Original source is unavailable or ambiguous")
    source = matches[0]
    if (
        source["kind"] != "raw"
        or source["fingerprint"]["sha256"] != anchor["sourceSha256"]
    ):
        raise SoundPlanningError("Source anchor requires the exact current original")


def _source_occurrence(anchor, cmap):
    if cmap.get("layoutMode") == "placed":
        from .import_layout import active_placements

        if "placementId" not in anchor:
            raise SoundPlanningError(
                "Placed source anchors require a placement selector"
            )
        values = list(
            active_placements(
                cmap, placement_id=anchor["placementId"], track_id=anchor.get("trackId")
            )
        )
    else:
        if "segmentId" not in anchor:
            raise SoundPlanningError(
                "Contiguous source anchors require a segment selector"
            )
        values = [
            row
            for row in cmap.get("segments", [])
            if row["segmentId"] == anchor["segmentId"]
        ]
    values = [row for row in values if row["sourceId"] == anchor["sourceId"]]
    if len(values) != 1:
        raise SoundPlanningError("Source occurrence is unavailable or ambiguous")
    return values[0]


def _timed_source_point(anchor, value):
    if value.get("mediaKind") == "still" or "pictureSampling" in value:
        raise SoundPlanningError(
            "Source anchors require qualified one-to-one timed media"
        )
    point = _time(anchor["sourceTime"])
    if not _time(value["in"]) <= point < _time(value["out"]):
        raise SoundPlanningError(
            "Source point is outside its retained half-open occurrence"
        )


def source_anchor_time(anchor, cmap):
    """Resolve selected original-source time through CMap; metadata only."""
    try:
        validate_document(anchor, "avo.sound-selection.schema.json#/$defs/sourceAnchor")
        if not isinstance(cmap, dict):
            raise SoundPlanningError("Current canonical source map is unavailable")
        _check_budget(cmap, METADATA_LIMITS)
        _source_record(anchor, cmap)
        _timed_source_point(anchor, _source_occurrence(anchor, cmap))
        point = anchor["sourceTime"]
        ticks = cmap_raw_to_output(
            cmap,
            anchor["sourceId"],
            point["ticks"],
            raw_timebase=point["timebase"],
            segment_id=anchor.get("segmentId"),
            placement_id=anchor.get("placementId"),
            track_id=anchor.get("trackId"),
        )
        if ticks is None:
            raise SoundPlanningError("Source point has no current program mapping")
        return {
            "ticks": ticks,
            "timebase": cmap_output_timebase(cmap),
            "domain": "cmap-output",
        }
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise SoundPlanningError(str(error)) from error


def _owning_component(anchor, cue, animation):
    references = {
        value
        for value in (
            cue.get("componentRef"),
            (cue.get("contentRef") or {}).get("componentId"),
        )
        if value is not None
    }
    if references != {anchor["componentId"]}:
        raise SoundPlanningError(
            "Camera anchor needs the exact unambiguous owning cue component"
        )
    matches = [
        component
        for component in (animation or {}).get("components", [])
        if component["componentId"] == anchor["componentId"]
    ]
    if len(matches) != 1:
        raise SoundPlanningError(
            "Canonical camera anchor component is unavailable or ambiguous"
        )
    return matches[0]


def _camera_wrapper(anchor, cue, animation):
    component = _owning_component(anchor, cue, animation)
    wrapper = (component.get("extensions") or {}).get("editingCraft")
    validate_document(wrapper, "avo.animation.schema.json#/$defs/editingCraft")
    camera = wrapper["camera"]
    _behavior(_encoded(camera))
    if camera["targetLayerId"] != cue.get("targetLayerId"):
        raise SoundPlanningError(
            "Camera anchor target differs from its owning picture layer"
        )
    if wrapper.get("sourceSha256") != anchor["sourceSha256"]:
        raise SoundPlanningError("Camera anchor source changed")
    return wrapper


def sound_phase(intent, part, animation=None):
    anchor = intent.get("cameraAnchor")
    if anchor is None:
        return Fraction(str(intent.get("phase", 0)))
    validate_document(anchor, "avo.sound-selection.schema.json#/$defs/cameraAnchor")
    wrapper = _camera_wrapper(anchor, part.get("cue") or {}, animation)
    camera = wrapper["camera"]
    digest = content_hash(
        {"behavior": camera, "geometry": wrapper.get("sourceGeometry")}
    )
    if digest != anchor["pathHash"]:
        raise SoundPlanningError("Camera anchor path changed")
    if anchor["nodeIndex"] >= len(camera["nodes"]):
        raise SoundPlanningError("Camera anchor node is unavailable")
    return Fraction(str(camera["nodes"][anchor["nodeIndex"]]["phase"]))
