"""Pure joins from selected relative camera intent to canonical source occurrences."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from fractions import Fraction
from itertools import pairwise

from avo.editing_craft import validate_editing_craft_selection

from .camera import (
    MAX_SCHEDULE_FRAMES,
    CameraError,
    evaluate_camera,
    validate_camera_schedule,
)
from .contracts import content_hash, validate_document
from .event_clock import sample_rate_boundary

BASELINE = {"scale": 1, "center": {"x": 0.5, "y": 0.5}}


def _seconds(ticks, timebase):
    if (
        type(ticks) is not int
        or ticks < 0
        or any(
            type(timebase[key]) is not int or timebase[key] <= 0
            for key in ("num", "den")
        )
    ):
        raise CameraError(
            "camera timing requires nonnegative ticks and a positive rational clock"
        )
    return Fraction(ticks * timebase["num"], timebase["den"])


def _frame(timing, fps):
    value = _seconds(timing["ticks"], timing["timebase"]) * fps
    return sample_rate_boundary(
        value.numerator, source_rate=value.denominator, target_rate=1
    )


def _components(strategy):
    return [
        component
        for component in strategy.get("components", [])
        if "camera" in ((component.get("extensions") or {}).get("editingCraft") or {})
    ]


def _selection(selection):
    if selection is None:
        raise CameraError("camera options must be frozen with the selected component")
    result = validate_editing_craft_selection(selection)
    camera = result["effective"]["camera"]
    if not camera["enabled"]:
        raise CameraError(
            "source-picture camera behavior requires explicit selected camera options"
        )
    if camera["faceAnchor"] != "off":
        raise CameraError(
            "selected face anchoring requires its qualified frozen subject trajectory"
        )
    return result["selectionHash"]


def _cue(component, cues, fps):
    matches = [
        cue
        for cue in cues
        if (cue.get("contentRef") or {}).get("componentId") == component["componentId"]
    ]
    if len(matches) != 1:
        raise CameraError(
            "each camera component requires one unambiguous canonical BMap cue"
        )
    cue = matches[0]
    if any(cue[key].get("domain") != "cmap-output" for key in ("start", "end")):
        raise CameraError("camera cue timing must remain owned by canonical BMap")
    frame_range = {
        "firstFrame": _frame(cue["start"], fps),
        "endFrameExclusive": _frame(cue["end"], fps),
    }
    if frame_range["endFrameExclusive"] <= frame_range["firstFrame"]:
        raise CameraError("camera cue does not contain a complete output frame")
    return cue, frame_range


def _layer(wrapper, cue, tracks):
    target = wrapper["camera"]["targetLayerId"]
    matches = [
        layer
        for layer in tracks.get("videoTracks", {}).get("layers", [])
        if layer["layerId"] == target
    ]
    if len(matches) != 1 or cue.get("targetLayerId") != target:
        raise CameraError("camera target does not identify its canonical source layer")
    layer = matches[0]
    if (layer.get("source") or {}).get("sha256") != wrapper.get("sourceSha256"):
        raise CameraError(
            "camera geometry/source fingerprint differs from its canonical target layer"
        )
    if not any(
        cue["cueId"] in region.get("cueIds", []) for region in layer.get("regions", [])
    ):
        raise CameraError("camera cue has no corresponding canonical source region")


def _contributions(video_graph):
    parts = []
    for operation in video_graph.get("operations", []):
        if operation["kind"] == "trim":
            parts.append(
                {
                    "occurrenceId": operation["operationId"],
                    "layerId": None,
                    "outputRange": operation["outputRange"],
                    **operation["parameters"],
                }
            )
        elif operation["kind"] == "source-layout":
            parts.extend(
                {
                    "occurrenceId": placement["placementId"],
                    "layerId": placement["trackId"],
                    **placement,
                }
                for placement in operation["parameters"]["placements"]
                if placement["enabled"] and placement["mediaKind"] == "video"
            )
    if len(parts) > 10000:
        raise CameraError("camera source occurrence budget exceeded")
    return parts


def _matching_parts(wrapper, parts, fps):
    camera = wrapper["camera"]
    if not camera.get("sourceId"):
        raise CameraError(
            "applied camera behavior requires an exact original source identity"
        )
    matches = [
        part
        for part in parts
        if part["sourceId"] == camera["sourceId"]
        and part["source"].get("sha256") == wrapper["sourceSha256"]
        and part["layerId"] in (None, camera["targetLayerId"])
    ]
    if not matches:
        raise CameraError(
            "camera target has no visible matching original source contribution"
        )
    for part in matches:
        _normal_speed(part, fps)
    return matches


def _normal_speed(part, fps):
    if part["source"].get("mediaClass") != "source":
        raise CameraError("camera transforms require admitted original-source picture")
    source = part["sourceRange"]
    duration = _seconds(source["endTicks"], source["timebase"]) - _seconds(
        source["startTicks"], source["timebase"]
    )
    extent = part["outputRange"]
    if (
        duration
        != Fraction(extent["endFrameExclusive"] - extent["startFrame"], 1) / fps
    ):
        raise CameraError("retimed or padded camera contributions are not qualified")


def _move(component, cues, tracks, parts, fps, selection):
    wrapper = component["extensions"]["editingCraft"]
    validate_document(wrapper, "avo.animation.schema.json#/$defs/editingCraft")
    if not {"sourceGeometry", "sourceSha256"} <= wrapper.keys():
        raise CameraError("camera source geometry and fingerprint remain unresolved")
    cue, interval = _cue(component, cues, fps)
    _layer(wrapper, cue, tracks)
    selected = _matching_parts(wrapper, parts, fps)
    identifier = (
        "camera-move-" + content_hash([component["componentId"], cue["cueId"]])[:24]
    )
    return {
        "optionsHash": _selection(wrapper.get("options", selection)),
        "moveId": identifier,
        "componentId": component["componentId"],
        "cueId": cue["cueId"],
        "behavior": wrapper["camera"],
        "geometry": wrapper["sourceGeometry"],
        "sourceSha256": wrapper["sourceSha256"],
        "entryPolicy": wrapper.get("entryPolicy", "continuous"),
        "frameRange": interval,
        "parts": selected,
        "propertyOwners": {"scale": identifier, "center": identifier},
    }


def _validate_group(group):
    selected = [
        {
            key: move[key]
            for key in ("moveId", "behavior", "frameRange", "propertyOwners")
        }
        for move in group
    ]
    validate_camera_schedule(selected, geometry=group[0]["geometry"])


def _validate_entries(layer):
    groups, active, prior = [], [], BASELINE
    for move in layer:
        if move["entryPolicy"] == "source-cut":
            if not any(
                part["outputRange"]["startFrame"] == move["frameRange"]["firstFrame"]
                for part in move["parts"]
            ):
                raise CameraError(
                    "cut-to-close entry must coincide with an actual visible source cut"
                )
            if active:
                groups.append(active)
            active, prior = [], None
        if active and (
            active[-1]["geometry"] != move["geometry"]
            or active[-1]["sourceSha256"] != move["sourceSha256"]
        ):
            raise CameraError(
                "changed camera baseline/source requires an explicit source-cut entry"
            )
        move["entryState"] = evaluate_camera(
            move["behavior"],
            frame=move["frameRange"]["firstFrame"],
            frame_range=move["frameRange"],
            geometry=move["geometry"],
            predecessor=prior,
        )
        prior = evaluate_camera(
            move["behavior"],
            frame=move["frameRange"]["endFrameExclusive"] - 1,
            frame_range=move["frameRange"],
            geometry=move["geometry"],
        )
        active.append(move)
    groups.append(active)
    for group in groups:
        _validate_group(group)


def _ordered_moves(moves, program_end):
    if (
        sum(
            move["frameRange"]["endFrameExclusive"] - move["frameRange"]["firstFrame"]
            for move in moves
        )
        > MAX_SCHEDULE_FRAMES
    ):
        raise CameraError("camera validation exceeds its explicit frame budget")
    layers = defaultdict(list)
    for move in moves:
        layers[move["behavior"]["targetLayerId"]].append(move)
    result = []
    for layer in layers.values():
        layer.sort(key=lambda move: move["frameRange"]["firstFrame"])
        for previous, current in pairwise(layer):
            if (
                previous["frameRange"]["endFrameExclusive"]
                > current["frameRange"]["firstFrame"]
            ):
                raise CameraError("overlapping camera property owners on one layer")
        _validate_entries(layer)
        for index, move in enumerate(layer):
            move["holdEnd"] = (
                layer[index + 1]["frameRange"]["firstFrame"]
                if index + 1 < len(layer)
                else program_end
            )
        result.extend(layer)
    return result


def _operation(move, part, first, last, options_hash):
    identity = [move["moveId"], part["occurrenceId"], first, last]
    parameters = {
        "componentId": move["componentId"],
        "cueId": move["cueId"],
        "targetLayerId": move["behavior"]["targetLayerId"],
        "sourceId": part["sourceId"],
        "sourceOccurrenceId": part["occurrenceId"],
        "sourceSha256": move["sourceSha256"],
        "behavior": deepcopy(move["behavior"]),
        "geometry": deepcopy(move["geometry"]),
        "originalFrameRange": dict(move["frameRange"]),
        "entryState": deepcopy(move["entryState"]),
        "pathHash": content_hash(
            {"behavior": move["behavior"], "geometry": move["geometry"]}
        ),
        "optionsHash": options_hash,
    }
    return {
        "operationId": "camera-" + content_hash(identity)[:24],
        "kind": "camera-transform",
        "capability": "camera-transform-v1",
        "inputs": [part["sourceId"]],
        "outputRange": {"startFrame": first, "endFrameExclusive": last},
        "parameters": parameters,
    }


def _operations(moves):
    result = []
    for move in moves:
        count = 0
        for part in move["parts"]:
            first = max(
                move["frameRange"]["firstFrame"], part["outputRange"]["startFrame"]
            )
            last = min(move["holdEnd"], part["outputRange"]["endFrameExclusive"])
            if first < last:
                result.append(_operation(move, part, first, last, move["optionsHash"]))
                count += 1
                if len(result) > 10000:
                    raise CameraError("compiled camera operation budget exceeded")
        if not count:
            raise CameraError("camera cue has no visible original-source frames")
    return sorted(
        result,
        key=lambda operation: (
            operation["outputRange"]["startFrame"],
            operation["operationId"],
        ),
    )


def compile_camera_operations(
    strategy, *, bmap, tracks, video_graph, output, selection
):
    """Keep BMap's original interval when splitting or holding a selected path."""
    components = _components(strategy)
    if not components:
        return []
    if len(components) > 500:
        raise CameraError("camera concept budget exceeded")
    rate = output["frameRate"]
    fps = Fraction(rate["num"], rate["den"])
    parts = _contributions(video_graph)
    end = max((part["outputRange"]["endFrameExclusive"] for part in parts), default=0)
    moves = [
        _move(component, bmap.get("cues", []), tracks, parts, fps, selection)
        for component in components
    ]
    return _operations(_ordered_moves(moves, end))
