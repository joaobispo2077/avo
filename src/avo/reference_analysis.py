"""Data-only visual observations and selected-subject association."""

from itertools import pairwise

from .timeline.contracts import validate_document

SCHEMA = "avo.visual-motion-analysis.schema.json"


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


__all__ = ["associate_selected_face"]
