"""Data-only audio role/channel contracts, shared by Tracks and sound choices."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class TrackError(ValueError):
    pass


_LAYOUT_CHANNELS = {"mono": 1, "stereo": 2}


def normalize_audio_track_layer(layer: dict[str, Any]) -> dict[str, Any]:
    """Require an explicit, valid channel map without changing source role."""
    result = deepcopy(layer)
    source_layout = str(result.get("sourceLayout") or "")
    target_layout = str(result.get("targetLayout") or "")
    source_channels = _LAYOUT_CHANNELS.get(source_layout)
    target_channels = _LAYOUT_CHANNELS.get(target_layout)
    mapping = result.get("channelMap")
    if source_channels is None or target_channels is None:
        raise TrackError("unsupported channel layout")
    if not isinstance(mapping, list) or len(mapping) != target_channels:
        raise TrackError("channel map must name every target channel")
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value >= source_channels
        for value in mapping
    ):
        raise TrackError("channel map references a missing source channel")
    if result.get("role") not in {
        "dialogue",
        "source-audio",
        "music",
        "sfx",
        "ambience",
    }:
        raise TrackError("unsupported audio role")
    return result


def apply_event_role_defaults(event: dict[str, Any]) -> dict[str, Any]:
    """Apply conservative media-role defaults before event-clock resolution."""
    result = deepcopy(event)
    role = str(result.get("role") or "")
    effects = list(result.get("entryEffectIds") or [])
    if role == "main-scene" and effects and not result.get("syntheticEffectApproved"):
        raise TrackError("main-scene cannot receive automatic overlay SFX")
    if (
        role in {"overlay-image", "overlay-video", "authored-graphic"}
        and len(effects) > 1
        and not result.get("orderedMultiEffect")
    ):
        raise TrackError("ordinary overlays allow at most one entry SFX")
    if role == "comparison-only":
        result["render"] = False
    if role == "overlay-video":
        audio = result.get("audio") or {}
        audio.setdefault("retainSourceAudio", bool(result.get("sourceRef")))
        result["audio"] = audio
    result.setdefault("exitEffectIds", [])
    result.setdefault("exitAudioEnabled", False)
    return result
