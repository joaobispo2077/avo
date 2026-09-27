"""Media adapter compatibility surface for canonical video-track compilation."""

from __future__ import annotations

from copy import deepcopy
from itertools import pairwise
from typing import Any

from avo.timeline.tracks import VideoTrackError, compile_video_layers


def compose_media_layer(
    layer: dict[str, Any], *, canvas: dict[str, int]
) -> dict[str, Any]:
    """Describe direct image/video composition with truthful vertical treatment."""
    kind = str(layer.get("kind") or "")
    if kind not in {"image", "video"}:
        raise VideoTrackError(f"unsupported media layer kind: {kind}")
    width, height = int(layer.get("width") or 0), int(layer.get("height") or 0)
    if width <= 0 or height <= 0:
        raise VideoTrackError("media dimensions must be positive")
    visible_range = layer.get("visibleRange")
    if visible_range is not None:
        start = int(visible_range.get("startFrame", -1))
        end = int(visible_range.get("endFrameExclusive", -1))
        if start < 0 or end <= start:
            raise VideoTrackError("media layer has an invalid resolved visible range")
    vertical = kind == "video" and height > width and canvas["width"] > canvas["height"]
    return {
        "layerId": layer.get("layerId"),
        "source": layer.get("locator"),
        "timing": {
            "eventId": layer.get("eventId") or layer.get("layerId"),
            "programFrame": layer.get("programFrame"),
            "visibleRange": deepcopy(visible_range),
            "sourceRange": deepcopy(layer.get("sourceRange")),
        },
        "background": (
            {"mode": "mirrored-fill", "source": layer.get("locator"), "crop": "cover"}
            if vertical
            else None
        ),
        "foreground": {
            "mode": "contain",
            "source": layer.get("locator"),
            "preserveMotion": kind == "video",
        },
    }


def verify_video_movement(
    layer_id: str,
    frame_fingerprints: list[str],
    *,
    expected_motion: bool,
    confidence: float = 1.0,
) -> dict[str, Any]:
    """Distinguish a moving insert from a frozen render without guessing."""
    if not frame_fingerprints:
        return {
            "layerId": layer_id,
            "status": "needs-human-judgment",
            "variationCount": 0,
        }
    variation = sum(left != right for left, right in pairwise(frame_fingerprints))
    if confidence < 0.5:
        status = "needs-human-judgment"
    elif expected_motion and variation == 0:
        status = "fail"
    else:
        status = "pass"
    return {
        "layerId": layer_id,
        "status": status,
        "variationCount": variation,
        "confidence": confidence,
        "expectedMotion": expected_motion,
    }


__all__ = [
    "VideoTrackError",
    "compile_video_layers",
    "compose_media_layer",
    "verify_video_movement",
]
