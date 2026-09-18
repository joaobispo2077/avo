"""Deterministic canonical timeline → legacy EDL compatibility projection."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

from .contracts import content_hash


class ProjectionError(ValueError):
    pass


def _revision(artifact: dict[str, Any], revision_id: str | None) -> dict[str, Any]:
    selected = (
        revision_id
        or artifact.get("approvedRevisionId")
        or artifact.get("currentRevisionId")
    )
    for revision in artifact.get("revisions") or []:
        if revision.get("revisionId") == selected:
            return revision
    raise ProjectionError(f"CMap revision not found: {selected}")


def _seconds(value: dict[str, Any]) -> float:
    base = value["timebase"]
    return float(Fraction(int(value["ticks"]) * int(base["num"]), int(base["den"])))


def _source_audio_declaration(
    source: dict[str, Any],
) -> tuple[tuple[str, str, str] | None, str | None]:
    meta = source.get("streamMetadata") or {}
    if "audioStream" not in meta and "dialogueChannel" not in meta:
        return None, None
    source_id = str(source.get("sourceId") or "<unknown>")
    stream = str(meta.get("audioStream") or "").strip()
    channel = str(meta.get("dialogueChannel") or "").strip().lower()
    missing = []
    if not stream:
        missing.append("audioStream")
    if channel not in {"left", "right"}:
        missing.append("dialogueChannel (must be left or right)")
    if missing:
        return None, f"{source_id} missing/invalid {', '.join(missing)}"
    return (source_id, stream, channel), None


def _apply_audio_metadata(snapshot: dict[str, Any], edl: dict[str, Any]) -> None:
    declarations = []
    incomplete = []
    for source in snapshot.get("sources") or []:
        declaration, error = _source_audio_declaration(source)
        if error:
            incomplete.append(error)
        elif declaration:
            declarations.append(declaration)
    if incomplete:
        raise ProjectionError(
            "incomplete audio metadata: " + "; ".join(sorted(incomplete))
        )
    configs = {(stream, channel) for _, stream, channel in declarations}
    if len(configs) > 1:
        details = ", ".join(
            f"{source_id}=({stream}, {channel})"
            for source_id, stream, channel in sorted(declarations)
        )
        raise ProjectionError(f"conflicting audio metadata: {details}")
    if not configs:
        return
    stream, channel = next(iter(configs))
    edl["audio"] = {
        "main_source_stream": stream,
        "dialogue_channel": channel,
    }


def _apply_bmap_cues(
    edl: dict[str, Any],
    bmap: dict[str, Any],
    tracks: dict[str, Any] | None,
) -> None:
    beat_revision = _revision(bmap, None)
    cues = beat_revision["snapshot"].get("cues") or []
    if tracks is None:
        overlays, effects = [], []
        for cue in cues:
            start = _seconds(cue["start"])
            end = _seconds(cue["end"])
            content = deepcopy(cue.get("contentRef") or {})
            item = {
                **content,
                "start_in_output": start,
                "duration": max(0.0, end - start),
                "motion_brief_id": cue["cueId"],
                "purpose": cue.get("intent"),
            }
            if cue["kind"] == "music":
                raise ProjectionError(
                    "music cues require resolved Tracks; they cannot be projected as one-shot SFX"
                )
            if cue["kind"] == "sfx":
                item["gain_db"] = float((cue.get("audio") or {}).get("gainDb", -12.0))
                effects.append(item)
            else:
                overlays.append(item)
        if overlays:
            edl["overlays"] = overlays
        if effects:
            edl["sound_effects"] = effects
    edl["timeline_projection"]["bmapRevisionId"] = beat_revision["revisionId"]
    edl["timeline_projection"]["bmapRevisionHash"] = beat_revision["contentHash"]


def _apply_tracks(
    edl: dict[str, Any],
    bmap: dict[str, Any] | None,
    tracks: dict[str, Any],
) -> None:
    from .tracks import resolve_tracks

    track_revision = _revision(tracks, None)
    assembly = track_revision["snapshot"]
    cue_ids = {
        cue["cueId"]
        for cue in (
            (_revision(bmap, None)["snapshot"].get("cues") or [])
            if bmap is not None
            else []
        )
    }
    assembly = (
        resolve_tracks(assembly, cue_ids) if bmap is not None else deepcopy(assembly)
    )
    edl["timeline_projection"]["tracksRevisionId"] = track_revision["revisionId"]
    edl["timeline_projection"]["tracksRevisionHash"] = track_revision["contentHash"]
    edl["timeline_tracks"] = deepcopy(assembly)
    edl["timeline_projection"]["capabilities"] = [
        "audio-tracks",
        "video-tracks",
        "z-order",
        "music-beds",
        "captions-last",
    ]


def project_cmap_to_edl(
    cmap: dict[str, Any],
    *,
    revision_id: str | None = None,
    bmap: dict[str, Any] | None = None,
    tracks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    revision = _revision(cmap, revision_id)
    snapshot = revision["snapshot"]
    sources = {
        str(source["sourceId"]): str(source.get("locator") or source["sourceId"])
        for source in snapshot.get("sources") or []
    }
    ranges = []
    for segment in snapshot.get("segments") or []:
        item = {
            "source": str(segment["sourceId"]),
            "start": _seconds(segment["in"]),
            "end": _seconds(segment["out"]),
        }
        if segment.get("storySectionId"):
            item["story_section_id"] = segment["storySectionId"]
        ranges.append(item)
    if not ranges:
        raise ProjectionError("cannot project an empty CMap")
    edl: dict[str, Any] = {
        "version": 1,
        "story_map_approval": (
            "approved"
            if cmap.get("approvedRevisionId") == revision["revisionId"]
            else "pending"
        ),
        "sources": sources,
        "ranges": ranges,
        "timeline_projection": {
            "canonical": False,
            "generated": True,
            "cmapArtifactId": cmap.get("artifactId"),
            "cmapRevisionId": revision["revisionId"],
            "cmapRevisionHash": revision["contentHash"],
        },
    }
    _apply_audio_metadata(snapshot, edl)
    if bmap is not None:
        _apply_bmap_cues(edl, bmap, tracks)
    if tracks is not None:
        _apply_tracks(edl, bmap, tracks)
    edl["timeline_projection"]["projectionHash"] = content_hash(edl)
    return edl


def approved_sync_transform(sync_map: dict[str, Any]) -> dict[str, Any]:
    approved = sync_map.get("approvedRevisionId")
    if not approved:
        raise ProjectionError("sync correction requires an approved sync-map revision")
    revision = _revision(sync_map, approved)
    validation = revision["snapshot"].get("fullProgramValidation") or {}
    if validation.get("status") != "pass":
        raise ProjectionError("sync correction requires full-program validation PASS")
    return deepcopy(revision["snapshot"]["transform"])


def write_cmap_projection(
    workspace, cmap: dict[str, Any], *, revision_id: str | None = None
) -> tuple[Path, dict[str, Any]]:
    """Atomically write generated EDL and a hash-bound projection manifest."""
    from avo.paths import schema_path
    from avo.validate_edl import load_and_validate

    from .contracts import file_fingerprint
    from .store import atomic_write_json, now_iso

    edl = project_cmap_to_edl(cmap, revision_id=revision_id)
    edl_path = workspace.generated_edl
    atomic_write_json(edl_path, edl)
    load_and_validate(edl_path, schema_path=schema_path("edl.schema.json"))
    edl_fp = file_fingerprint(edl_path)
    manifest = {
        "schemaVersion": "1.0.0",
        "canonicalDirectory": "edit/timeline",
        "generatedEdlPath": "edit/edl.json",
        "canonicalFirst": True,
        "status": "generated",
        "cmapRevisionId": edl["timeline_projection"]["cmapRevisionId"],
        "cmapRevisionHash": edl["timeline_projection"]["cmapRevisionHash"],
        "projectionHash": edl["timeline_projection"]["projectionHash"],
        "edlSha256": edl_fp["sha256"],
        "generatedAt": now_iso(),
        "capabilities": ["cmap-ranges"],
    }
    atomic_write_json(workspace.timeline_dir / "projection.json", manifest)
    return edl_path, manifest


def verify_projection(workspace) -> dict[str, Any]:
    import json

    from .contracts import file_fingerprint

    manifest_path = workspace.timeline_dir / "projection.json"
    if not manifest_path.is_file() or not workspace.generated_edl.is_file():
        raise ProjectionError("projection or generated EDL is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = file_fingerprint(workspace.generated_edl)["sha256"]
    if actual != manifest.get("edlSha256"):
        raise ProjectionError("derived EDL modified outside canonical projection")
    return manifest


def write_assembly_projection(workspace: Any) -> tuple[Path, dict[str, Any]]:
    """Write exact active CMap+BMap+Tracks into the renderer compatibility EDL."""
    from avo.paths import schema_path
    from avo.validate_edl import load_and_validate

    from .contracts import file_fingerprint
    from .store import atomic_write_json, now_iso

    workspace.require_active("cmap")
    workspace.require_active("bmap")
    workspace.require_active("tracks")
    cmap = workspace.store("cmap").load()
    bmap = workspace.store("bmap").load()
    tracks = workspace.store("tracks").load()
    edl = project_cmap_to_edl(cmap, bmap=bmap, tracks=tracks)
    atomic_write_json(workspace.generated_edl, edl)
    load_and_validate(
        workspace.generated_edl, schema_path=schema_path("edl.schema.json")
    )
    fingerprint = file_fingerprint(workspace.generated_edl)
    projection = edl["timeline_projection"]
    manifest = {
        "schemaVersion": "1.0.0",
        "canonicalDirectory": "edit/timeline",
        "generatedEdlPath": "edit/edl.json",
        "canonicalFirst": True,
        "status": "generated",
        "cmapRevisionId": projection["cmapRevisionId"],
        "cmapRevisionHash": projection["cmapRevisionHash"],
        "bmapRevisionId": projection["bmapRevisionId"],
        "bmapRevisionHash": projection["bmapRevisionHash"],
        "tracksRevisionId": projection["tracksRevisionId"],
        "tracksRevisionHash": projection["tracksRevisionHash"],
        "projectionHash": projection["projectionHash"],
        "edlSha256": fingerprint["sha256"],
        "generatedAt": now_iso(),
        "capabilities": projection["capabilities"],
    }
    atomic_write_json(workspace.timeline_dir / "projection.json", manifest)
    return workspace.generated_edl, manifest
