"""Canonical materialization application services."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from avo.adapters.media.sync_materializer import SyncMaterializer


def _stat_identity(path: Path) -> dict[str, int]:
    stat = Path(path).stat()
    return {
        "sizeBytes": stat.st_size,
        "mtimeNs": stat.st_mtime_ns,
        "ctimeNs": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
    }


def _reuse_key(
    *,
    output_path: Path,
    canonical_input_lock: dict[str, Any],
    render_profile: str,
    projection_hash: str,
) -> str:
    from .contracts import content_hash

    return content_hash({
        "canonicalInputLock": canonical_input_lock,
        "renderProfile": render_profile,
        "projectionHash": projection_hash,
        "outputPath": str(Path(output_path)),
    })


def _reusable_cut_materialization(
    directory: Path,
    *,
    output_path: Path,
    canonical_input_lock: dict[str, Any],
    render_profile: str,
    projection_hash: str,
) -> dict[str, Any] | None:
    """Reuse exact unchanged output without rehashing or rerendering media."""
    import json

    cache_path = directory / "reuse-cache.json"
    if not cache_path.is_file() or not Path(output_path).is_file():
        return None
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    key = _reuse_key(
        output_path=output_path,
        canonical_input_lock=canonical_input_lock,
        render_profile=render_profile,
        projection_hash=projection_hash,
    )
    entry = (cache.get("entries") or {}).get(key)
    if not entry or entry.get("outputStat") != _stat_identity(output_path):
        return None
    record_path = directory / str(entry.get("recordFile") or "")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    from .contracts import content_hash

    expected = content_hash(
        {name: value for name, value in record.items() if name != "materializationHash"}
    )
    output = record.get("output") or {}
    locator = str(output.get("locator") or output.get("path") or "")
    if (
        record.get("materializationHash") != expected
        or record.get("canonicalInputLock") != canonical_input_lock
        or record.get("renderProfile") != render_profile
        or record.get("projectionHash") != projection_hash
        or locator != str(Path(output_path))
    ):
        return None
    return record


def _remember_reusable_cut(
    directory: Path,
    *,
    record_path: Path,
    output_path: Path,
    canonical_input_lock: dict[str, Any],
    render_profile: str,
    projection_hash: str,
) -> None:
    import json

    from .store import atomic_write_json

    cache_path = directory / "reuse-cache.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {"schemaVersion": "1.0.0", "entries": {}}
    key = _reuse_key(
        output_path=output_path,
        canonical_input_lock=canonical_input_lock,
        render_profile=render_profile,
        projection_hash=projection_hash,
    )
    cache.setdefault("entries", {})[key] = {
        "recordFile": record_path.name,
        "outputStat": _stat_identity(output_path),
    }
    atomic_write_json(cache_path, cache)


def materialize_synced_raw(
    *,
    picture_path: Path,
    audio_path: Path,
    output_path: Path,
    sync_revision: dict[str, Any],
    expected_picture_sha256: str | None = None,
    expected_audio_sha256: str | None = None,
    materializer: SyncMaterializer | None = None,
) -> dict[str, Any]:
    snapshot = sync_revision.get("snapshot") or {}
    if snapshot.get("status") == "not-applicable":
        raise ValueError("not-applicable Sync has no correction to materialize")
    revision_hash = str(sync_revision.get("contentHash") or sync_revision.get("contentSha256") or "")
    if len(revision_hash) != 64:
        raise ValueError("Sync materialization requires exact approved revision hash")
    return (materializer or SyncMaterializer()).materialize(
        picture_path=picture_path,
        audio_path=audio_path,
        output_path=output_path,
        transform=snapshot["transform"],
        sync_revision_hash=revision_hash,
        expected_picture_sha256=expected_picture_sha256,
        expected_audio_sha256=expected_audio_sha256,
    )


def materialize_cut_proof(
    *,
    workspace: Any,
    cmap_revision_id: str,
    output_path: Path,
    render_port: Any | None = None,
    render_profile: str = "draft",
) -> dict[str, Any]:
    """Project current CMap and render an immutable hash-bound cut proof."""
    import json

    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    from .contracts import content_hash
    from .projection import write_cmap_projection
    from .store import atomic_write_json, now_iso

    store = workspace.store("cmap")
    revision = store.revision(cmap_revision_id)
    if revision["snapshot"].get("syncRef") is None:
        raise ValueError("CMap cut proof requires exact Sync/N/A basis")
    if store.load_index()["headRevisionId"] != cmap_revision_id:
        raise ValueError("cut proof must render the current CMap head")

    edl_path, projection = write_cmap_projection(
        workspace,
        store.load(),
        revision_id=cmap_revision_id,
    )
    lock = {
        "cmapRevisionId": cmap_revision_id,
        "cmapRevisionHash": revision["contentHash"],
        "syncRevisionId": revision["snapshot"]["syncRef"]["revisionId"],
        "syncRevisionHash": revision["snapshot"]["syncRef"]["contentSha256"],
        "rawFingerprints": {
            source["sourceId"]: source["fingerprint"]["sha256"]
            for source in revision["snapshot"].get("sources") or []
        },
    }
    directory = workspace.timeline_dir / "materializations" / "cut-proof"
    reusable = _reusable_cut_materialization(
        directory,
        output_path=Path(output_path),
        canonical_input_lock=lock,
        render_profile=render_profile,
        projection_hash=projection["projectionHash"],
    )
    if reusable is not None:
        return reusable

    rendered = (render_port or TimelineRenderAdapter()).render(
        edl_path,
        Path(output_path),
        profile=render_profile,
    )
    materialization_id = (
        f"cut-proof-{cmap_revision_id}-{rendered['output']['sha256'][:12]}"
    )
    target = (
        workspace.timeline_dir
        / "materializations"
        / "cut-proof"
        / f"{materialization_id}.json"
    )
    invariant = {
        "schemaVersion": "1.0.0",
        "kind": "cut-proof",
        "materializationId": materialization_id,
        "cmapRevisionId": cmap_revision_id,
        "canonicalInputLock": lock,
        "renderProfile": render_profile,
        "projectionHash": projection["projectionHash"],
        "output": rendered["output"],
        "producer": rendered["producer"],
    }
    if target.is_file():
        existing = json.loads(target.read_text(encoding="utf-8"))
        existing_invariant = {
            key: value
            for key, value in existing.items()
            if key not in {"createdAt", "materializationHash"}
        }
        if existing_invariant != invariant:
            raise ValueError(f"immutable materialization collision: {target}")
        expected_hash = content_hash(
            {key: value for key, value in existing.items() if key != "materializationHash"}
        )
        if existing.get("materializationHash") != expected_hash:
            raise ValueError(f"immutable materialization hash mismatch: {target}")
        _remember_reusable_cut(
            directory, record_path=target, output_path=output_path,
            canonical_input_lock=lock, render_profile=render_profile,
            projection_hash=projection["projectionHash"],
        )
        return existing

    record = {**invariant, "createdAt": now_iso()}
    record["materializationHash"] = content_hash(record)
    atomic_write_json(target, record)
    _remember_reusable_cut(
        directory, record_path=target, output_path=output_path,
        canonical_input_lock=lock, render_profile=render_profile,
        projection_hash=projection["projectionHash"],
    )
    return record
