"""Pure, frame-addressable source framing. This module does not render or author.

Centers are normalized to the declared baseline crop. Safe regions instead refer
to the complete original display space (SAR corrected, then rotated). Frame
ranges stay outside the relative Animation behavior and always use the original
full cue interval, including when a caller requests a small render window.
"""

from __future__ import annotations

import json
import math
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
