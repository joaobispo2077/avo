"""Data-only visual observations and selected-subject association."""

from copy import deepcopy
from fractions import Fraction
from itertools import pairwise
from math import isfinite
from statistics import median

from .reference_timing import interpret_reference_timing
from .timeline.contracts import content_hash, validate_document

SCHEMA = "avo.visual-motion-analysis.schema.json"
ASSOCIATION_PARAMETERS = ("seed", "minimumOverlap", "maximumGapTicks")


def _seed_index(frames, seed):
    for index, frame in enumerate(frames):
        if frame["sourceTick"] == seed["sourceTick"]:
            if seed["detectionIndex"] < len(frame["detections"]):
                return index
            break
    raise ValueError("Face selection requires an exact sampled detection")


def _validate_frame_sequence(frames):
    if any(b["sourceTick"] <= a["sourceTick"] for a, b in pairwise(frames)):
        raise ValueError("Face observations require strictly increasing source ticks")
    for frame in frames:
        for detection in frame["detections"]:
            x, y, width, height = detection["box"]
            if not (
                x + width <= 1
                and y + height <= 1
                and width * height > 0
                and 0 <= detection["score"] <= 1
            ):
                raise ValueError("Face detection exceeds display bounds or score range")


def _intersection_over_union(first, second):
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    width = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    height = max(0, min(ay + ah, by + bh) - max(ay, by))
    intersection = width * height
    return min(1.0, intersection / (aw * ah + bw * bh - intersection))


def _observation(frame, status, index=None, overlap=None):
    return {
        "sourceTick": frame["sourceTick"],
        "status": status,
        "detectionIndex": index,
        "overlap": overlap,
    }


def _follow_face(previous_box, first, frame, request):
    if previous_box is None:
        return _observation(frame, "reseed-required")
    if frame["sourceTick"] - first > request["maximumGapTicks"]:
        return _observation(frame, "gap")
    matches = []
    for index, candidate in enumerate(frame["detections"]):
        overlap = _intersection_over_union(previous_box, candidate["box"])
        if overlap >= request["minimumOverlap"]:
            matches.append((index, overlap))
    if len(matches) == 1:
        return _observation(frame, "selected", *matches[0])
    return _observation(frame, "ambiguous" if matches else "lost")


def associate_selected_face(request):
    """Follow local geometric overlap from a selected seed on the source clock."""
    validate_document(request, SCHEMA)
    if not 0 < request["minimumOverlap"] <= 1:
        raise ValueError("Face overlap threshold must be finite and positive")
    frames, seed = request["frames"], request["seed"]
    _validate_frame_sequence(frames)
    start = _seed_index(frames, seed)
    result = [_observation(frame, "unselected") for frame in frames[:start]]
    selected = seed["detectionIndex"]
    result.append(_observation(frames[start], "selected", selected))
    for first, frame in pairwise(frames[start:]):
        box = first["detections"][selected]["box"] if selected is not None else None
        observation = _follow_face(box, first["sourceTick"], frame, request)
        selected = observation["detectionIndex"]
        result.append(observation)
    validate_document(result, SCHEMA + "#/$defs/faceAssociation")
    return result


def _display_box(detection, rect):
    x, y, width, height = detection["box"]
    if not all(isfinite(value) for value in (x, y, width, height)):
        raise ValueError("Proxy face box must be finite")
    if width <= 0 or height <= 0 or not 0 <= detection["score"] <= 1:
        raise ValueError("Proxy face box or detector score is invalid")
    left, top, content_width, content_height = (
        rect[key] for key in ("x", "y", "width", "height")
    )
    first_x, first_y = max(x, left), max(y, top)
    last_x = min(x + width, left + content_width)
    last_y = min(y + height, top + content_height)
    if first_x >= last_x or first_y >= last_y:
        return None
    return {
        "box": [
            (first_x - left) / content_width,
            (first_y - top) / content_height,
            (last_x - first_x) / content_width,
            (last_y - first_y) / content_height,
        ],
        "score": detection["score"],
    }


def map_proxy_face_samples(observed, source_ticks, content_rect):
    """Map bounded pixel observations onto an explicit original-source frame grid."""
    for value, definition in (
        (observed, "proxyDetectionRows"),
        (source_ticks, "sampledSourceTicks"),
        (content_rect, "proxyContentRect"),
    ):
        validate_document(value, SCHEMA + "#/$defs/" + definition)
    if len(observed) != len(source_ticks):
        raise ValueError(
            "Detection samples require exact source ticks for every proxy frame"
        )
    frames = [
        {
            "sourceTick": tick,
            "detections": [
                mapped
                for detection in rows
                if (mapped := _display_box(detection, content_rect)) is not None
            ],
        }
        for tick, rows in zip(source_ticks, observed, strict=True)
    ]
    _validate_frame_sequence(frames)
    return frames


def _display_aspect(geometry):
    sar = geometry["sampleAspectRatio"]
    aspect = Fraction(geometry["width"] * sar["num"], geometry["height"] * sar["den"])
    return 1 / aspect if geometry["rotation"] in (90, 270) else aspect


def _require_observation_scope(request, observed):
    proxy, scope = request["proxy"], request["sourceRange"]
    if observed.get("proxySha256") != proxy["sha256"]:
        raise ValueError("Face observations differ from the selected proxy identity")
    if any(
        not scope["startTicks"] <= tick < scope["endTicks"]
        for tick in proxy["sourceTicks"]
    ):
        raise ValueError(
            "Every sampled frame must lie inside the selected source range"
        )
    rect = proxy["content"]
    if (
        rect["x"] + rect["width"] > proxy["width"]
        or rect["y"] + rect["height"] > proxy["height"]
    ):
        raise ValueError("Face proxy content lies outside its display frame")
    aspect = _display_aspect(request["geometry"])
    if (
        abs(rect["width"] - rect["height"] * aspect) > 1
        and abs(rect["height"] - rect["width"] / aspect) > 1
    ):
        raise ValueError("Face proxy differs from the original display aspect")


def freeze_face_observation(request, observed):
    """Bind measured proxy facts and association to exact source and detector inputs."""
    validate_document(request, SCHEMA + "#/$defs/faceObservationRequest")
    _require_observation_scope(request, observed)
    proxy = request["proxy"]
    frames = map_proxy_face_samples(
        observed["detections"], proxy["sourceTicks"], proxy["content"]
    )
    association = associate_selected_face(
        {
            "frames": frames,
            **{key: request[key] for key in ASSOCIATION_PARAMETERS},
        }
    )
    identity = ("modelSha256", "device", "isolated", "versions")
    result = {
        "contractVersion": "1.0.0",
        "request": deepcopy(request),
        "detector": {key: deepcopy(observed[key]) for key in identity},
        "samples": frames,
        "association": association,
        "coverage": {
            "observedFrames": len(frames),
            "selectedFrames": sum(item["status"] == "selected" for item in association),
        },
    }
    result["analysisHash"] = content_hash(result)
    validate_document(result, SCHEMA + "#/$defs/faceObservation")
    return result


def _require_face_observation(observation):
    validate_document(observation, SCHEMA + "#/$defs/faceObservation")
    payload = {
        key: value for key, value in observation.items() if key != "analysisHash"
    }
    if observation["analysisHash"] != content_hash(payload):
        raise ValueError("Face observation identity changed")


def _trajectory_points(frames, association):
    points = []
    for frame, item in zip(frames, association, strict=True):
        if item["status"] == "selected":
            box = frame["detections"][item["detectionIndex"]]["box"]
            points.append({"sourceTick": item["sourceTick"], "box": deepcopy(box)})
    centers = [
        [x + width / 2, y + height / 2]
        for x, y, width, height in (point["box"] for point in points)
    ]
    for index, point in enumerate(points):
        neighbors = (
            centers[index - 1 : index + 2]
            if 0 < index < len(centers) - 1
            else centers[index : index + 1]
        )
        x, y = map(median, zip(*neighbors, strict=True))
        point["center"] = {"x": x, "y": y}
    return points


def _append_uncertainty(intervals, start, end, reason):
    if start >= end:
        return
    if (
        intervals
        and intervals[-1]["endTicks"] == start
        and intervals[-1]["reason"] == reason
    ):
        intervals[-1]["endTicks"] = end
    else:
        intervals.append({"startTicks": start, "endTicks": end, "reason": reason})


def _uncertain_intervals(association, scope):
    intervals = []
    _append_uncertainty(
        intervals, scope["startTicks"], association[0]["sourceTick"], "unobserved"
    )
    stop = {"sourceTick": scope["endTicks"], "status": "unobserved"}
    for current, following in pairwise([*association, stop]):
        start, end, reason = (
            current["sourceTick"],
            following["sourceTick"],
            current["status"],
        )
        if reason == "selected":
            if following["status"] == "selected":
                continue
            start, reason = start + 1, "unobserved"
        _append_uncertainty(intervals, start, end, reason)
    return intervals


def freeze_face_trajectory(observation):
    """Smooth measured framing offline and expose exact uncertainty for review."""
    _require_face_observation(observation)
    request, frames = observation["request"], observation["samples"]
    scope, proxy = request["sourceRange"], request["proxy"]
    _require_observation_scope(request, {"proxySha256": proxy["sha256"]})
    association = associate_selected_face(
        {"frames": frames, **{key: request[key] for key in ASSOCIATION_PARAMETERS}}
    )
    if [frame["sourceTick"] for frame in frames] != proxy[
        "sourceTicks"
    ] or association != observation["association"]:
        raise ValueError(
            "Face observation samples or association differ from the frozen selection"
        )
    result = {
        "contractVersion": "1.0.0",
        "observationHash": observation["analysisHash"],
        "smoothing": "median-three-v1",
        "streamOriginTicks": request.get("streamOriginTicks"),
        **{
            key: deepcopy(request[key]) for key in ("source", "sourceRange", "geometry")
        },
        "points": _trajectory_points(frames, association),
        "uncertainIntervals": _uncertain_intervals(association, scope),
    }
    result["trajectoryHash"] = content_hash(result)
    validate_document(result, SCHEMA + "#/$defs/faceTrajectory")
    return result


def _visual_interval(start, end, measured, aspects):
    result = {"startTicks": start, "endTicks": end}
    if "brightness" in aspects:
        result["brightness"] = deepcopy(measured["brightness"])
    if "scene-changes" in aspects:
        result["cutCandidate"] = measured["status"] == "cut-candidate"
    if aspects.intersection(("global-motion", "element-motion")):
        result["motionStatus"] = measured["status"]
        if "reason" in measured:
            result["reason"] = measured["reason"]
        else:
            result["coverage"] = deepcopy(measured["coverage"])
            for aspect, metric in (
                ("global-motion", "global"),
                ("element-motion", "residual"),
            ):
                if aspect in aspects:
                    result[metric] = deepcopy(measured[metric])
    return result


def _require_reference_pairs(request, observed):
    ticks = request["proxy"]["sourceTicks"]
    pairs = observed["pairs"]
    validate_document(pairs, SCHEMA + "#/$defs/referencePairs")
    gaps = [second - first for first, second in pairwise(ticks)]
    if len(pairs) != len(gaps) or min(gaps) <= 0:
        raise ValueError(
            "Reference measurements require an exact increasing sampled frame grid"
        )
    for pair in pairs:
        coverage = pair.get("coverage")
        if coverage and (
            coverage["inliers"] > coverage["tracked"]
            or pair["residual"]["movingPoints"] > coverage["tracked"]
        ):
            raise ValueError(
                "Reference motion coverage exceeds observed feature tracks"
            )
    return pairs, ticks, gaps


def freeze_reference_motion(request, observed, *, audio=None):
    """Store selected measured aspects on native time, separately from interpretation."""
    validate_document(request, SCHEMA + "#/$defs/referenceObservationRequest")
    _require_observation_scope(request, observed)
    pairs, ticks, gaps = _require_reference_pairs(request, observed)
    aspects = set(request["aspects"])
    result = {
        "contractVersion": "1.0.0",
        "request": deepcopy(request),
        "runtime": {
            key: deepcopy(observed[key])
            for key in ("isolated", "device", "versions", "method")
        },
        "coverage": {
            "sampledFrames": len(ticks),
            "pairCount": len(pairs),
            "minimumGapTicks": min(gaps),
            "maximumGapTicks": max(gaps),
        },
        "intervals": [
            _visual_interval(first, last, pair, aspects)
            for (first, last), pair in zip(pairwise(ticks), pairs, strict=True)
        ],
        "interpretation": interpret_reference_timing(
            ticks, pairs, aspects, request["sourceRange"], audio=audio
        ),
    }
    result["analysisHash"] = content_hash(result)
    validate_document(result, SCHEMA + "#/$defs/referenceObservation")
    return result


__all__ = [
    "associate_selected_face",
    "freeze_face_observation",
    "freeze_face_trajectory",
    "freeze_reference_motion",
    "map_proxy_face_samples",
]
