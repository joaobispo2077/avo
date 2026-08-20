"""Compile inspectable video Tracks into overlay and caption layers."""

from __future__ import annotations

from typing import Any


class VideoTrackError(ValueError):
    """Raised when a visual layer cannot be compiled safely."""


_OVERLAY_ROLES = {"clip", "image", "text", "card", "graphic", "overlay"}
_ALLOWED_COMPOSITE = {None, "normal", "over", "alpha"}


def _seconds(ticks: int, timebase: dict[str, int] | None = None) -> float:
    num = int((timebase or {}).get("num", 1))
    den = int((timebase or {}).get("den", 1000))
    return float(ticks) * num / den


def compile_video_layers(layers: list[dict[str, Any]]) -> dict[str, Any]:
    """Compile z-ordered overlays and keep captions last."""
    ordered = sorted(
        layers,
        key=lambda item: (
            item.get("zOrder", item.get("order", 0)),
            item.get("layerId", ""),
        ),
    )
    overlays: list[dict[str, Any]] = []
    captions: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = []
    for layer in ordered:
        role = str(layer.get("role") or "")
        composite = (layer.get("composite") or {}).get("mode")
        if composite not in _ALLOWED_COMPOSITE:
            raise VideoTrackError(f"unsupported composite mode: {composite}")
        if role in _OVERLAY_ROLES and not layer.get("faceAvoidance", False):
            raise VideoTrackError(f"face avoidance required for {layer.get('layerId')}")
        region = (layer.get("regions") or [{}])[0]
        start = _seconds(int(region.get("startTicks") or 0), region.get("timebase"))
        end = _seconds(int(region.get("endTicks") or 0), region.get("timebase"))
        locator = str((layer.get("source") or {}).get("locator") or "")
        item = {
            "layerId": layer.get("layerId"),
            "role": role,
            "file": locator,
            "start_in_output": start,
            "duration": max(0.0, end - start),
            "zOrder": layer.get("zOrder", 0),
        }
        if role == "caption":
            captions = item
        elif role != "base":
            overlays.append(item)
        trace.append(
            {"layerId": layer.get("layerId"), "role": role, "zOrder": item["zOrder"]}
        )
    if captions is not None:
        trace = [item for item in trace if item["role"] != "caption"]
        trace.append(
            {
                "layerId": captions["layerId"],
                "role": "caption",
                "zOrder": captions["zOrder"],
            }
        )
    return {"overlays": overlays, "captions": captions, "trace": trace}
