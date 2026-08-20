"""Resolved inspectable assembly layers derived from BMap intent."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import file_fingerprint
from .workspace import TimelineWorkspace


class TrackError(ValueError):
    pass


def resolve_tracks(
    snapshot: dict[str, Any],
    cue_ids: set[str],
    *,
    cues: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = deepcopy(snapshot)
    for group in ("audioTracks", "videoTracks"):
        layers = result.get(group, {}).get("layers") or []
        seen: set[str] = set()
        for layer in layers:
            layer_id = str(layer.get("layerId") or "")
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
