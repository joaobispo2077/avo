"""Pure, frame-addressable source framing. This module does not render or author.

Centers are normalized to the declared baseline crop. Safe regions instead refer
to the complete original display space (SAR corrected, then rotated). Frame
ranges stay outside the relative Animation behavior and always use the original
full cue interval, including when a caller requests a small render window.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from itertools import pairwise

from .contracts import canonical_json_bytes, validate_document

CURVES = {
    "hold",
    "linear",
    "quadratic-in",
    "quadratic-out",
    "quadratic-in-out",
    "quartic-in",
    "exponential-out",
}
MAX_SCHEDULE_FRAMES = 2_000_000
MAX_FACE_FRAMES = 256
WIDE_STATE = (Fraction(1), Fraction(1, 2), Fraction(1, 2))


class CameraError(ValueError):
    """A relative framing path cannot satisfy its declared source constraints."""


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        raise CameraError(f"{name} requires a finite number")
    if isinstance(value, float) and not math.isfinite(value):
        raise CameraError(f"{name} requires a finite number")
    return value if isinstance(value, Fraction) else Fraction(str(value))


def ease_curve(name, phase):
    """Version 1 named curves, with exact initial/final endpoint rules."""
    if not isinstance(name, str) or name not in CURVES:
        raise CameraError("unsupported named camera curve")
    phase = _number(phase, "phase")
    if not 0 <= phase <= 1:
        raise CameraError("curve phase must lie in [0, 1]")
    if phase in (0, 1):
        return phase
    return _curve_interior(name, phase)


def _curve_interior(name, phase):
    if name == "hold":
        return Fraction(0)
    if name == "linear":
        return phase
    if name == "quadratic-in":
        return phase**2
    if name == "quadratic-out":
        return 1 - (1 - phase) ** 2
    if name == "quadratic-in-out":
        return 2 * phase**2 if phase < Fraction(1, 2) else 1 - 2 * (1 - phase) ** 2
    if name == "quartic-in":
        return phase**4
    return 1 - 2 ** (-10 * float(phase))


def _schema(value, name):
    try:
        validate_document(value, f"avo.camera-behavior.schema.json{name}")
    except (ValueError, TypeError, RecursionError) as exc:
        raise CameraError(f"invalid camera input: {str(exc)[:400]}") from exc


def _encoded(value):
    try:
        return canonical_json_bytes(value)
    except (ValueError, TypeError, RecursionError) as exc:
        raise CameraError(f"invalid camera input: {str(exc)[:300]}") from exc


def _state(node):
    return (
        _number(node["scale"], "scale"),
        _number(node["center"]["x"], "center.x"),
        _number(node["center"]["y"], "center.y"),
    )


@lru_cache(maxsize=64)
def _behavior(encoded):
    value = json.loads(encoded)
    _schema(value, "")
    nodes = tuple(
        (_number(node["phase"], "phase"), _state(node), node["curve"])
        for node in value["nodes"]
    )
    phases = [node[0] for node in nodes]
    if (
        phases[0] != 0
        or phases[-1] != 1
        or any(left >= right for left, right in pairwise(phases))
    ):
        raise CameraError("camera nodes require strictly increasing phase from 0 to 1")
    return nodes, _regions(value.get("safeRegions", []))


def _regions(selected):
    regions, seen = [], set()
    for region in selected:
        if region["regionId"] in seen:
            raise CameraError("duplicate protected safe region identity")
        seen.add(region["regionId"])
        rect = tuple(
            _number(region["rect"][key], key) for key in ("x", "y", "width", "height")
        )
        if rect[0] + rect[2] > 1 or rect[1] + rect[3] > 1:
            raise CameraError("protected safe region exceeds source display bounds")
        regions.append(
            (region["regionId"], rect, _number(region["clearance"], "clearance"))
        )
    return tuple(regions)


def display_size(geometry):
    """Return exact display dimensions, correcting SAR before orientation."""
    _schema(geometry, "#/$defs/geometry")
    width = Fraction(geometry["codedWidth"]) * Fraction(
        int(geometry["sampleAspectRatio"]["num"]),
        int(geometry["sampleAspectRatio"]["den"]),
    )
    height = Fraction(geometry["codedHeight"])
    return (height, width) if geometry["rotationDegrees"] % 180 else (width, height)


@lru_cache(maxsize=64)
def _geometry(encoded):
    value = json.loads(encoded)
    size = display_size(value)
    baseline = tuple(
        _number(value["baselineCrop"][key], key)
        for key in ("x", "y", "width", "height")
    )
    margin = value.get("cropMargin", {})
    margins = tuple(
        _number(margin.get(key, 0), key) for key in ("left", "right", "top", "bottom")
    )
    _check_crop(baseline, size, (Fraction(0),) * 4)
    return size, baseline, margins


@lru_cache(maxsize=64)
def _interval(encoded):
    frame_range = json.loads(encoded)
    _schema(frame_range, "#/$defs/frameRange")
    first, end = frame_range["firstFrame"], frame_range["endFrameExclusive"]
    if type(first) is not int or type(end) is not int:
        raise CameraError("camera frame interval requires exact integers")
    if end <= first:
        raise CameraError("camera frame interval must be nonempty")
    return first, end


def _prepared(behavior, frame_range, geometry, predecessor):
    nodes, regions = _behavior(_encoded(behavior))
    first, end = _interval(_encoded(frame_range))
    if end - first == 1 and any(node[1] != nodes[0][1] for node in nodes):
        raise CameraError("a one-frame camera interval supports a hold only")
    if predecessor is not None:
        _check_predecessor(predecessor, nodes[0][1])
    return nodes, regions, first, end, _geometry(_encoded(geometry))


def _check_predecessor(predecessor, expected):
    try:
        actual = _state(predecessor)
    except (KeyError, TypeError) as exc:
        raise CameraError(
            "camera predecessor requires its actual scale and center"
        ) from exc
    if actual != expected:
        raise CameraError(
            "camera predecessor continuity does not match declared entry state"
        )


def _interpolate(nodes, phase):
    if phase <= 0:
        return nodes[0][1]
    if phase >= 1:
        return nodes[-1][1]
    for left, right in pairwise(nodes):
        if phase <= right[0]:
            local = (phase - left[0]) / (right[0] - left[0])
            eased = _number(ease_curve(left[2], local), "evaluated curve")
            return tuple(a + (b - a) * eased for a, b in zip(left[1], right[1]))
    raise CameraError("camera path does not cover normalized phase")


def _crop(state, baseline):
    scale, center_x, center_y = state
    x, y, width, height = baseline
    cropped_width, cropped_height = width / scale, height / scale
    return (
        x + width * center_x - cropped_width / 2,
        y + height * center_y - cropped_height / 2,
        cropped_width,
        cropped_height,
    )


def _check_crop(crop, size, margins):
    x, y, width, height = crop
    left, right, top, bottom = margins
    if (
        x < left
        or y < top
        or x + width > size[0] - right
        or y + height > size[1] - bottom
    ):
        raise CameraError("camera crop violates original display bounds or crop margin")


def _check_regions(crop, size, regions):
    x, y, width, height = crop
    for region_id, rect, clearance in regions:
        rx, ry, rw, rh = rect
        source = (rx * size[0], ry * size[1], (rx + rw) * size[0], (ry + rh) * size[1])
        allowed = (
            x + clearance * width,
            y + clearance * height,
            x + (1 - clearance) * width,
            y + (1 - clearance) * height,
        )
        if (
            source[0] < allowed[0]
            or source[1] < allowed[1]
            or source[2] > allowed[2]
            or source[3] > allowed[3]
        ):
            raise CameraError(f"camera crop obscures protected safe region {region_id}")


def _evaluate(prepared, frame):
    nodes, regions, first, end, source = prepared
    size, baseline, margins = source
    phase = (
        Fraction(0) if end - first == 1 else Fraction(frame - first, end - first - 1)
    )
    phase = max(Fraction(0), min(Fraction(1), phase))
    state = _interpolate(nodes, phase)
    crop = _crop(state, baseline)
    _check_crop(crop, size, margins)
    _check_regions(crop, size, regions)
    output_crop = {
        key: _finite_output(value)
        for key, value in zip(("x", "y", "width", "height"), crop)
    }
    if output_crop["width"] <= 0 or output_crop["height"] <= 0:
        raise CameraError("camera crop exceeds supported finite numeric precision")
    return {
        "scale": _finite_output(state[0]),
        "center": {"x": _finite_output(state[1]), "y": _finite_output(state[2])},
        "crop": output_crop,
        "phase": float(phase),
    }


def _finite_output(value):
    try:
        result = float(value)
    except OverflowError as exc:
        raise CameraError(
            "camera state exceeds supported finite numeric precision"
        ) from exc
    if not math.isfinite(result):
        raise CameraError("camera state exceeds supported finite numeric precision")
    return result


def evaluate_camera(behavior, *, frame, frame_range, geometry, predecessor=None):
    """Evaluate one frame against the full original interval, in any seek order."""
    if type(frame) is not int:
        raise CameraError("camera frame index requires an integer")
    prepared = _prepared(behavior, frame_range, geometry, predecessor)
    return _evaluate(prepared, frame)


def _blend(first, last, amount):
    return tuple(a + (b - a) * amount for a, b in zip(first, last, strict=True))


def _face_pose(tick, ticks, values):
    if not ticks[0] <= tick <= ticks[-1]:
        return None
    left = bisect_right(ticks, tick) - 1
    if left == len(ticks) - 1:
        return values[left]
    right = left + 1
    amount = Fraction(tick - ticks[left]) / (ticks[right] - ticks[left])
    return _blend(values[left], values[right], amount)


def _face_axis(amount, center, target, left, length, width, low, high, display):
    wanted = center + (target * display - left - length * center) / length * amount
    minimum = max(Fraction(0), (low + width / 2 - left) / length)
    maximum = min(Fraction(1), (display - high - width / 2 - left) / length)
    if minimum > maximum:
        raise CameraError(
            "Face anchor scale cannot fit inside the declared camera margins"
        )
    epsilon = min(Fraction(1, 10**9), (maximum - minimum) / 2)
    return min(maximum - epsilon, max(minimum + epsilon, wanted))


def _face_center(state, pose, amount, prepared_geometry):
    if not amount:
        return state
    (width, height), (x, y, w, h), (left, right, top, bottom) = prepared_geometry
    scale, center_x, center_y = state
    return (
        scale,
        _face_axis(amount, center_x, pose[0], x, w, w / scale, left, right, width),
        _face_axis(amount, center_y, pose[1], y, h, h / scale, top, bottom, height),
    )


def _transition(distance, span):
    return ease_curve("quadratic-in-out", Fraction(min(distance, span), span))


def _leading_states(entry, count, transition, fallback):
    if fallback == "static":
        return [
            _blend(entry, WIDE_STATE, _transition(i, transition)) for i in range(count)
        ]
    return [entry] * count


def _trailing_states(previous, count, transition, fallback):
    if fallback == "static":
        length = min(count, transition)
        return [
            _blend(previous, WIDE_STATE, _transition(i + 1, length))
            for i in range(count)
        ]
    return [previous] * count


def _tracked_states(base, poses, bounds, *, transition, geometry, leading, source_cut):
    first, last = bounds
    exit_blend = last == len(poses) - 1
    tracked = []
    for index in range(first, last + 1):
        travel = _transition(index - first, transition)
        if not leading and source_cut:
            travel = Fraction(1)
        base_state = (
            _blend(leading[-1], base[index], travel) if leading else base[index]
        )
        release = _transition(last - index, transition) if exit_blend else Fraction(1)
        tracked.append(
            _face_center(base_state, poses[index], min(travel, release), geometry)
        )
    return tracked


def _freeze_face_nodes(behavior, states):
    denominator = len(states) - 1
    nodes = []
    for index, (scale, x, y) in enumerate(states):
        state = {
            "scale": _finite_output(scale),
            "center": {"x": _finite_output(x), "y": _finite_output(y)},
        }
        # The compiled states belong to exact integer output frames. A hold
        # changes halfway between adjacent frame times, avoiding an inexact
        # decimal phase boundary when seeking the integer sample itself.
        phase = (
            (index - 0.5) / denominator
            if 0 < index < denominator
            else index / denominator
        )
        nodes.append(_recipe_node(phase, state))
    return {**behavior, "nodes": nodes}


def _check_tracked_faces(anchored, poses, frame_range, geometry):
    prepared = _prepared(anchored, frame_range, geometry, None)
    nodes, _, first, end, (size, baseline, _) = prepared
    for index, pose in enumerate(poses):
        if pose is not None:
            state = _interpolate(nodes, Fraction(index, end - first - 1))
            _check_regions(
                _crop(state, baseline), size, [("selected face", pose[2:], 0)]
            )
        _evaluate(prepared, first + index)


def _face_poses(points, source_ticks):
    ticks = [point["sourceTick"] for point in points]
    values = [
        tuple(
            _number(value, "face trajectory")
            for value in (point["center"]["x"], point["center"]["y"], *point["box"])
        )
        for point in points
    ]
    return [_face_pose(tick, ticks, values) for tick in source_ticks]


def _face_bounds(poses, fallback):
    trusted = [index for index, pose in enumerate(poses) if pose is not None]
    if not trusted:
        raise CameraError("Camera cue has no measured frames for the selected face")
    if len(trusted) != len(poses) and fallback not in {"hold", "static"}:
        raise CameraError("Uncertain face frames require a reviewed fallback")
    return trusted[0], trusted[-1]


def reframe_face_camera(
    behavior,
    *,
    frame_range,
    geometry,
    points,
    source_ticks,
    transition_frames,
    fallback,
    source_cut=False,
):
    """Resolve frozen display points to an ordinary seekable camera behavior."""
    count = frame_range["endFrameExclusive"] - frame_range["firstFrame"]
    if not 2 <= count <= MAX_FACE_FRAMES or len(source_ticks) != count:
        raise CameraError(
            "Face anchoring requires 2 to 256 exact camera frames per cue"
        )
    nodes, _, _, _, prepared_geometry = _prepared(behavior, frame_range, geometry, None)
    poses = _face_poses(points, source_ticks)
    first, last = _face_bounds(poses, fallback)
    base = [_interpolate(nodes, Fraction(i, count - 1)) for i in range(count)]
    lead = _leading_states(base[0], first, transition_frames, fallback)
    tracked = _tracked_states(
        base,
        poses,
        (first, last),
        transition=transition_frames,
        geometry=prepared_geometry,
        leading=lead,
        source_cut=source_cut,
    )
    tail = _trailing_states(tracked[-1], count - last - 1, transition_frames, fallback)
    anchored = _freeze_face_nodes(behavior, [*lead, *tracked, *tail])
    _check_tracked_faces(anchored, poses, frame_range, geometry)
    return anchored


def _owners(move):
    owners = move["propertyOwners"]
    if owners["scale"] != move["moveId"] or owners["center"] != move["moveId"]:
        raise CameraError("camera framing properties require one resolved move owner")


def _schedule_intervals(moves):
    by_layer, identities = {}, set()
    for move in moves:
        if move["moveId"] in identities:
            raise CameraError("duplicate camera move owner identity")
        identities.add(move["moveId"])
        _owners(move)
        by_layer.setdefault(move["behavior"]["targetLayerId"], []).append(move)
    for layer in by_layer.values():
        ordered = sorted(layer, key=lambda move: move["frameRange"]["firstFrame"])
        for previous, current in pairwise(ordered):
            if (
                previous["frameRange"]["endFrameExclusive"]
                > current["frameRange"]["firstFrame"]
            ):
                raise CameraError(
                    "overlapping camera framing owners on one target layer"
                )
            if _state(previous["behavior"]["nodes"][-1]) != _state(
                current["behavior"]["nodes"][0]
            ):
                raise CameraError(
                    "camera schedule predecessor continuity would introduce a jump"
                )


def validate_camera_schedule(moves, *, geometry):
    """Validate every sampled framing state and one owner per target/property.

    This proves numeric/crop constraints only. It does not prove encoded fidelity,
    source admission, editorial suitability or creator approval.
    """
    _schema(moves, "#/$defs/schedule")
    _schedule_intervals(moves)
    frames = sum(
        move["frameRange"]["endFrameExclusive"] - move["frameRange"]["firstFrame"]
        for move in moves
    )
    if frames > MAX_SCHEDULE_FRAMES:
        raise CameraError("camera validation exceeds its explicit frame budget")
    for move in moves:
        prepared = _prepared(move["behavior"], move["frameRange"], geometry, None)
        for frame in range(prepared[2], prepared[3]):
            _evaluate(prepared, frame)


CAMERA_TREATMENTS = frozenset(
    {
        "push",
        "pull",
        "punch-settle",
        "cut-to-close",
        "speed-contrast",
        "overlay-return",
        "section-alternate",
        "section-drift",
    }
)


def _recipe_options(options, preset, face_anchor):
    from avo.editing_craft import validate_editing_craft_selection

    selected = validate_editing_craft_selection(options)
    camera = selected["effective"]["camera"]
    if not camera["enabled"]:
        raise CameraError("camera recipes require explicitly selected enabled options")
    if (camera["faceAnchor"] == "selected-subject") != (face_anchor is not None):
        raise CameraError(
            "selected face anchoring requires its frozen subject trajectory"
        )
    required = {
        "section-alternate": {"alternate", "alternate-and-push"},
        "section-drift": {"push", "alternate-and-push"},
    }
    if preset in required and camera["baseTreatment"] not in required[preset]:
        raise CameraError(
            "section recipe requires its explicitly selected base treatment"
        )
    return selected


def _recipe_state(value):
    if not isinstance(value, dict) or set(value) - {"scale", "center", "crop", "phase"}:
        raise CameraError("camera recipe requires a declared framing state")
    _schema(value["center"], "#/$defs/center")
    scale, x, y = _state(value)
    if scale <= 0:
        raise CameraError("camera recipe state requires a positive scale")
    return {
        "scale": _finite_output(scale),
        "center": {"x": _finite_output(x), "y": _finite_output(y)},
    }


def _recipe_target(preset, entry, scale, center):
    restore = preset in {"pull", "overlay-return"}
    alternate_wide = preset == "section-alternate" and entry["scale"] > 1
    if restore or alternate_wide:
        default = 1
    elif preset == "section-drift":
        default = entry["scale"] * 1.03
    else:
        default = 1.12
    if alternate_wide:
        scale = 1
    baseline_center = restore or preset in {"section-alternate", "cut-to-close"}
    target = _recipe_state(
        {
            "scale": default if scale is None else scale,
            "center": center
            if center is not None
            else ({"x": 0.5, "y": 0.5} if baseline_center else entry["center"]),
        }
    )
    _recipe_direction(preset, entry, target)
    return target


def _recipe_direction(preset, entry, target):
    if (
        preset in {"push", "punch-settle", "speed-contrast", "section-drift"}
        and target["scale"] <= entry["scale"]
    ):
        raise CameraError("push target must exceed the actual predecessor scale")
    if preset == "pull" and target["scale"] > entry["scale"]:
        raise CameraError("pull target cannot increase the actual predecessor scale")
    if preset == "overlay-return" and target != {
        "scale": 1,
        "center": {"x": 0.5, "y": 0.5},
    }:
        raise CameraError("overlay-return must finish at the declared baseline")


def _recipe_node(phase, state, curve="hold"):
    return {"phase": phase, **deepcopy(state), "curve": curve}


def _recipe_nodes(preset, entry, target):
    if preset in {"cut-to-close", "section-alternate"}:
        return [_recipe_node(0, target), _recipe_node(1, target)], "source-cut"
    if preset == "punch-settle":
        settled = {
            **target,
            "scale": entry["scale"] + (target["scale"] - entry["scale"]) * 0.75,
        }
        return [
            _recipe_node(0, entry, "exponential-out"),
            _recipe_node(0.25, target, "quadratic-out"),
            _recipe_node(0.5, settled),
            _recipe_node(1, settled),
        ], "continuous"
    if preset == "speed-contrast":
        pause = {
            **target,
            "scale": entry["scale"] + (target["scale"] - entry["scale"]) * 0.6,
        }
        return [
            _recipe_node(0, entry, "exponential-out"),
            _recipe_node(0.2, pause),
            _recipe_node(0.65, pause, "quadratic-in-out"),
            _recipe_node(1, target),
        ], "continuous"
    if preset == "overlay-return":
        return [
            _recipe_node(0, entry, "quadratic-in-out"),
            _recipe_node(0.75, target),
            _recipe_node(1, target),
        ], "continuous"
    curve = "linear" if preset == "section-drift" else "quadratic-in-out"
    return [_recipe_node(0, entry, curve), _recipe_node(1, target)], "continuous"


def _validate_recipe_geometry(wrapper):
    validate_document(wrapper, "avo.animation.schema.json#/$defs/editingCraft")
    nodes, regions = _behavior(_encoded(wrapper["camera"]))
    size, baseline, margins = _geometry(_encoded(wrapper["sourceGeometry"]))
    for _, state, _ in nodes:
        crop = _crop(state, baseline)
        _check_crop(crop, size, margins)
        _check_regions(crop, size, regions)


def make_camera_treatment(
    preset,
    *,
    target_layer_id,
    source_id,
    source_sha256,
    geometry,
    options,
    predecessor=None,
    target_scale=None,
    target_center=None,
    safe_regions=(),
    face_anchor=None,
):
    """Build selected untimed intent; canonical compilation still validates every frame.

    Source-cut entries remain requests until matched to an actual visible cut.
    No detector, source probe, render, preference write or timing publication runs.
    """
    if not isinstance(preset, str) or preset not in CAMERA_TREATMENTS:
        raise CameraError("unknown selected camera recipe")
    try:
        selected = _recipe_options(options, preset, face_anchor)
        entry = _recipe_state(
            predecessor
            if predecessor is not None
            else {"scale": 1, "center": {"x": 0.5, "y": 0.5}}
        )
        target = _recipe_target(preset, entry, target_scale, target_center)
        nodes, policy = _recipe_nodes(preset, entry, target)
        behavior = {
            "contractVersion": "1.0.0",
            "targetLayerId": target_layer_id,
            "sourceId": source_id,
            "nodes": nodes,
        }
        if not isinstance(safe_regions, (list, tuple)) or len(safe_regions) > 64:
            raise CameraError(
                "camera safe regions require a bounded explicit collection"
            )
        if safe_regions:
            behavior["safeRegions"] = deepcopy(list(safe_regions))
        wrapper = {
            "camera": behavior,
            "sourceGeometry": deepcopy(geometry),
            "sourceSha256": source_sha256,
            "options": deepcopy(selected),
            "entryPolicy": policy,
        }
        if face_anchor is not None:
            wrapper["faceAnchor"] = deepcopy(face_anchor)
        _validate_recipe_geometry(wrapper)
        return wrapper
    except (ValueError, TypeError, KeyError, OverflowError, ZeroDivisionError) as error:
        if isinstance(error, CameraError):
            raise
        raise CameraError(f"invalid selected camera recipe: {error}") from error
