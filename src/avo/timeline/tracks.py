"""Resolved inspectable assembly layers derived from BMap intent."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from avo.breath_control import resolve_control, select_events

from .contracts import file_fingerprint, validate_document
from .workspace import TimelineWorkspace


class TrackError(ValueError):
    pass


class VideoTrackError(ValueError):
    """Raised when a visual layer cannot be compiled safely."""


_OVERLAY_ROLES = {"clip", "image", "text", "card", "graphic", "overlay"}
_ALLOWED_COMPOSITE = {None, "normal", "over", "alpha"}


def _seconds(ticks: int, timebase: dict[str, int] | None = None) -> float:
    num = int((timebase or {}).get("num", 1))
    den = int((timebase or {}).get("den", 1000))
    return float(ticks) * num / den


def _validated_video_role(layer: dict[str, Any]) -> str:
    role = str(layer.get("role") or "")
    composite = (layer.get("composite") or {}).get("mode")
    if composite not in _ALLOWED_COMPOSITE:
        raise VideoTrackError(f"unsupported composite mode: {composite}")
    if role in _OVERLAY_ROLES and not layer.get("faceAvoidance", False):
        raise VideoTrackError(f"face avoidance required for {layer.get('layerId')}")
    return role


def _compile_video_layer(
    layer: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    role = _validated_video_role(layer)
    region = (layer.get("regions") or [{}])[0]
    start = _seconds(int(region.get("startTicks") or 0), region.get("timebase"))
    end = _seconds(int(region.get("endTicks") or 0), region.get("timebase"))
    item = {
        "layerId": layer.get("layerId"),
        "role": role,
        "file": str((layer.get("source") or {}).get("locator") or ""),
        "start_in_output": start,
        "duration": max(0.0, end - start),
        "zOrder": layer.get("zOrder", 0),
    }
    trace = {"layerId": item["layerId"], "role": role, "zOrder": item["zOrder"]}
    return role, item, trace


def _captions_last(
    trace: list[dict[str, Any]], captions: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if captions is None:
        return trace
    without_captions = [item for item in trace if item["role"] != "caption"]
    without_captions.append(
        {
            "layerId": captions["layerId"],
            "role": "caption",
            "zOrder": captions["zOrder"],
        }
    )
    return without_captions


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
        role, item, trace_item = _compile_video_layer(layer)
        if role == "caption":
            captions = item
        elif role != "base":
            overlays.append(item)
        trace.append(trace_item)
    return {
        "overlays": overlays,
        "captions": captions,
        "trace": _captions_last(trace, captions),
    }


def _validate_breath_layer(layer: dict) -> None:
    control = layer.get("breathControl")
    if not resolve_control(control, role=str(layer.get("role") or "")):
        return
    validate_document(control, "avo.breath-control.schema.json")
    if control.get("sourceSha256") != (layer.get("source") or {}).get("sha256"):
        raise TrackError("breath source fingerprint is missing or stale")
    select_events(control, 48000)


def resolve_tracks(
    snapshot: dict[str, Any],
    cue_ids: set[str],
    *,
    cues: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = deepcopy(snapshot)
    for group in ("audioTracks", "videoTracks"):
        layers = result.get(group, {}).get("layers") or []
        if group == "audioTracks":
            layers = [
                normalize_audio_track_layer(layer)
                if any(
                    key in layer
                    for key in ("sourceLayout", "targetLayout", "channelMap")
                )
                else layer
                for layer in layers
            ]
        seen: set[str] = set()
        for layer in layers:
            layer_id = str(layer.get("layerId") or "")
            _validate_breath_layer(layer)
            if not layer_id or layer_id in seen:
                raise TrackError("track layer IDs must be unique and stable")
            seen.add(layer_id)
            source = layer.get("source") or {}
            locator = source.get("locator")
            if locator:
                path = Path(locator)
                if not path.is_file():
                    raise TrackError(f"source missing: {layer_id}")
                actual = file_fingerprint(path)["sha256"]
                if actual != source.get("sha256"):
                    raise TrackError(f"source fingerprint mismatch: {layer_id}")
            if source.get("actualSha256") and source.get("actualSha256") != source.get(
                "sha256"
            ):
                raise TrackError(f"source fingerprint mismatch: {layer_id}")
            for region in layer.get("regions") or []:
                linked = set(region.get("cueIds") or [])
                missing = linked - cue_ids
                if missing:
                    raise TrackError(f"unresolved BMap cues: {sorted(missing)}")
                has_range = "startTicks" in region and "endTicks" in region
                if has_range and int(region["endTicks"]) <= int(region["startTicks"]):
                    raise TrackError(f"invalid region range: {layer_id}")
                if cues and has_range:
                    for cue_id in linked:
                        cue = cues[cue_id]
                        cue_start = int(cue["start"]["ticks"])
                        cue_end = int(cue["end"]["ticks"])
                        if (
                            int(region["startTicks"]) > cue_start
                            or int(region["endTicks"]) < cue_end
                        ):
                            raise TrackError(
                                f"track region invents/truncates cue timing: {layer_id}/{cue_id}"
                            )
        result.setdefault(group, {})["layers"] = sorted(
            layers, key=lambda item: (item.get("order", 0), item.get("layerId", ""))
        )
    return result


def inspect_audio_hierarchy(layers: list[dict[str, Any]]) -> list[str]:
    findings = []
    dialogue = next((item for item in layers if item.get("role") == "dialogue"), None)
    if dialogue and dialogue.get("channels") not in ([0, 1], [0]):
        findings.append("dialogue-channel-mapping")
    if dialogue and dialogue.get("channels") == [0]:
        findings.append("dialogue-channel-mapping")
    for layer in layers:
        if (
            layer.get("role") == "music"
            and float(layer.get("gainDb", 0))
            >= float((dialogue or {}).get("gainDb", 0)) - 6
            and not layer.get("ducking")
        ):
            findings.append("music-masks-dialogue")
    return findings


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


def inspect_visual_hierarchy(layers: list[dict[str, Any]]) -> list[str]:
    findings = []
    for layer in layers:
        if layer.get("role") in {
            "overlay",
            "text",
            "card",
            "graphic",
            "image",
            "clip",
        } and not layer.get("faceAvoidance", False):
            findings.append("face-avoidance")
    return sorted(set(findings))


class TracksService:
    def __init__(self, workspace: TimelineWorkspace):
        self.workspace = workspace
        self.store = workspace.store("tracks")

    def _basis(self) -> tuple[dict[str, Any], dict[str, Any]]:
        bmap_store = self.workspace.store("bmap")
        bmap_index = self.workspace.require_active("bmap")
        revision = bmap_store.revision(bmap_index["headRevisionId"])
        basis = {
            "artifactType": "bmap",
            "artifactId": bmap_index["artifactId"],
            "revisionId": revision["revisionId"],
            "sha256": revision["contentHash"],
            "state": "valid",
        }
        return basis, revision

    def author(
        self, snapshot: dict[str, Any], *, actor: str, reason: str
    ) -> dict[str, Any]:
        basis, bmap_revision = self._basis()
        value = deepcopy(snapshot)
        value["basis"] = basis
        value["cmapBasis"] = deepcopy(bmap_revision["snapshot"]["basis"])
        cue_map = {
            cue["cueId"]: cue for cue in bmap_revision["snapshot"].get("cues") or []
        }
        value = resolve_tracks(value, set(cue_map), cues=cue_map)
        index = self.store.load_index()
        expected = None
        if index["headRevisionId"]:
            expected = self.store.revision(index["headRevisionId"])["contentHash"]
        revision = self.store.append_revision(
            snapshot=value,
            actor=actor,
            reason=reason,
            dependencies=[
                {
                    "artifactType": "bmap",
                    "artifactId": basis["artifactId"],
                    "revisionId": basis["revisionId"],
                    "contentSha256": basis["sha256"],
                }
            ],
            expected_head_hash=expected,
        )
        if expected and expected != revision["contentHash"]:
            self.workspace.invalidate_descendants(
                "tracks",
                before_hash=expected,
                after_hash=revision["contentHash"],
                reason="Tracks revision changed",
                actor=actor,
            )
        revision["editlogRefresh"] = self.workspace.notify_editlog()
        return revision

    def inspect(self) -> dict[str, Any]:
        index = self.workspace.require_active("tracks")
        revision = self.store.revision(index["headRevisionId"])
        snapshot = revision["snapshot"]
        return {
            "revisionId": revision["revisionId"],
            "revisionHash": revision["contentHash"],
            "basis": snapshot["basis"],
            "audioLayers": snapshot["audioTracks"]["layers"],
            "videoLayers": snapshot["videoTracks"]["layers"],
            "audioFindings": inspect_audio_hierarchy(snapshot["audioTracks"]["layers"]),
            "visualFindings": inspect_visual_hierarchy(
                snapshot["videoTracks"]["layers"]
            ),
        }


def audit_contributions(
    snapshot: dict[str, Any],
    rendered_trace: list[dict[str, Any]],
) -> dict[str, Any]:
    declared = {
        layer["layerId"]
        for group in ("audioTracks", "videoTracks")
        for layer in (snapshot.get(group) or {}).get("layers") or []
        if not layer.get("mute") and layer.get("status") != "disabled"
    }
    rendered = {item["layerId"] for item in rendered_trace if item.get("enabled", True)}
    missing = sorted(declared - rendered)
    unexpected = sorted(rendered - declared)
    return {
        "status": "pass" if not missing and not unexpected else "fail",
        "declared": sorted(declared),
        "rendered": sorted(rendered),
        "missing": missing,
        "unexpected": unexpected,
    }
