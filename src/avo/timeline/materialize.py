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

    return content_hash(
        {
            "canonicalInputLock": canonical_input_lock,
            "renderProfile": render_profile,
            "projectionHash": projection_hash,
            "outputPath": str(Path(output_path)),
        }
    )


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
    revision_hash = str(
        sync_revision.get("contentHash") or sync_revision.get("contentSha256") or ""
    )
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
            {
                key: value
                for key, value in existing.items()
                if key != "materializationHash"
            }
        )
        if existing.get("materializationHash") != expected_hash:
            raise ValueError(f"immutable materialization hash mismatch: {target}")
        _remember_reusable_cut(
            directory,
            record_path=target,
            output_path=output_path,
            canonical_input_lock=lock,
            render_profile=render_profile,
            projection_hash=projection["projectionHash"],
        )
        return existing

    record = {**invariant, "createdAt": now_iso()}
    record["materializationHash"] = content_hash(record)
    atomic_write_json(target, record)
    _remember_reusable_cut(
        directory,
        record_path=target,
        output_path=output_path,
        canonical_input_lock=lock,
        render_profile=render_profile,
        projection_hash=projection["projectionHash"],
    )
    return record


def _assembly_reuse_key(
    *,
    output_path: Path,
    canonical_input_lock: dict[str, Any],
    render_profile: str,
    projection_hash: str,
    render_contract_hash: str,
    policy_hash: str,
) -> str:
    from .contracts import content_hash

    return content_hash(
        {
            "outputPath": str(Path(output_path).resolve()),
            "canonicalInputLock": canonical_input_lock,
            "renderProfile": render_profile,
            "projectionHash": projection_hash,
            "renderContractHash": render_contract_hash,
            "deliveryFidelityPolicyHash": policy_hash,
        }
    )


def _reusable_assembly_materialization(
    directory: Path,
    *,
    reuse_key: str,
    output_path: Path,
) -> dict[str, Any] | None:
    import json

    from .contracts import content_hash, file_fingerprint

    cache_path = directory / "reuse-cache.json"
    if not cache_path.is_file() or not output_path.is_file():
        return None
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        entry = (cache.get("entries") or {})[reuse_key]
        record_path = directory / str(entry["recordFile"])
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (KeyError, OSError, TypeError, ValueError):
        return None
    expected = content_hash(
        {key: value for key, value in record.items() if key != "materializationHash"}
    )
    if record.get("materializationHash") != expected:
        raise ValueError(
            f"immutable assembly materialization hash mismatch: {record_path}"
        )
    if file_fingerprint(output_path) != record.get("output"):
        return None
    return record


def _remember_reusable_assembly(
    directory: Path,
    *,
    reuse_key: str,
    record_path: Path,
) -> None:
    import json

    from .store import atomic_write_json

    cache_path = directory / "reuse-cache.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {"schemaVersion": "1.0.0", "entries": {}}
    cache.setdefault("entries", {})[reuse_key] = {"recordFile": record_path.name}
    atomic_write_json(cache_path, cache)


def _validated_policy_hash(
    render_contract: dict[str, Any], policy: dict[str, Any]
) -> str:
    from .contracts import content_hash

    if policy.get("renderContract") != render_contract:
        raise ValueError("delivery-fidelity policy and render contract disagree")
    policy_hash = content_hash(
        {key: value for key, value in policy.items() if key != "policyHash"}
    )
    if policy.get("policyHash") != policy_hash:
        raise ValueError("delivery-fidelity policy hash is invalid")
    return policy_hash


def _assembly_render_hash(
    *,
    lock: dict[str, Any],
    projection_hash: str,
    render_profile: str,
    contract_hash: str,
    policy_hash: str,
    output_path: Path,
) -> str:
    from .contracts import content_hash

    return content_hash(
        {
            "canonicalInputLock": lock,
            "projectionHash": projection_hash,
            "renderProfile": render_profile,
            "renderContractHash": contract_hash,
            "deliveryFidelityPolicyHash": policy_hash,
            "outputPath": str(output_path),
        }
    )


def _render_assembly_output(
    *,
    render_port: Any,
    projection_path: Path,
    output_path: Path,
    render_profile: str,
    render_contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    from .contracts import file_fingerprint

    rendered = render_port.render(
        projection_path,
        output_path,
        profile=render_profile,
        render_contract=render_contract,
    )
    actual_output = file_fingerprint(output_path)
    if (rendered.get("output") or {}).get("sha256") != actual_output["sha256"]:
        raise ValueError("renderer output fingerprint does not match rendered bytes")
    return rendered, actual_output


def _assembly_invariant(
    *,
    materialization_id: str,
    lock: dict[str, Any],
    projection_hash: str,
    render_profile: str,
    render_contract: dict[str, Any],
    contract_hash: str,
    render_hash: str,
    lineage: dict[str, Any],
    policy: dict[str, Any],
    policy_hash: str,
    output: dict[str, Any],
    producer: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schemaVersion": "1.1.0",
        "kind": "assembly",
        "materializationId": materialization_id,
        "canonicalInputLock": lock,
        "projectionHash": projection_hash,
        "renderProfile": render_profile,
        "renderContract": render_contract,
        "renderContractHash": contract_hash,
        "renderHash": render_hash,
        "pictureLineage": lineage,
        "pictureLineageHash": lineage["pictureLineageHash"],
        "deliveryFidelityPolicy": policy,
        "deliveryFidelityPolicyHash": policy_hash,
        "output": output,
        "producer": producer or {"name": "timeline-render", "version": "unknown"},
    }


def _persist_assembly_record(
    target: Path, invariant: dict[str, Any], *, clock: Any
) -> dict[str, Any]:
    import json

    from .contracts import content_hash, validate_document
    from .store import atomic_write_json

    if target.is_file():
        existing = json.loads(target.read_text(encoding="utf-8"))
        existing_invariant = {
            key: value
            for key, value in existing.items()
            if key not in {"createdAt", "materializationHash"}
        }
        if existing_invariant != invariant:
            raise ValueError(f"immutable assembly materialization collision: {target}")
        expected_hash = content_hash(
            {
                key: value
                for key, value in existing.items()
                if key != "materializationHash"
            }
        )
        if existing.get("materializationHash") != expected_hash:
            raise ValueError(
                f"immutable assembly materialization hash mismatch: {target}"
            )
        return existing
    record = {**invariant, "createdAt": clock()}
    record["materializationHash"] = content_hash(record)
    validate_document(record, "avo.materialization.schema.json")
    atomic_write_json(target, record)
    return record


def materialize_assembly(
    *,
    workspace: Any,
    output_path: Path,
    render_contract: dict[str, Any],
    delivery_fidelity_policy: dict[str, Any],
    render_port: Any | None = None,
    render_profile: str = "delivery",
) -> dict[str, Any]:
    """Render and immutably bind a complete canonical timeline assembly."""
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    from .contracts import content_hash
    from .picture_lineage import build_picture_lineage, current_assembly_lock
    from .projection import write_assembly_projection
    from .store import now_iso

    lock, revisions = current_assembly_lock(workspace)
    policy_hash = _validated_policy_hash(render_contract, delivery_fidelity_policy)
    projection_path, projection = write_assembly_projection(workspace)
    projection_hash = str(projection["projectionHash"])
    contract_hash = content_hash(render_contract)
    output_path = Path(output_path).resolve()
    render_hash = _assembly_render_hash(
        lock=lock,
        projection_hash=projection_hash,
        render_profile=render_profile,
        contract_hash=contract_hash,
        policy_hash=policy_hash,
        output_path=output_path,
    )
    directory = workspace.timeline_dir / "materializations" / "assembly"
    reuse_key = _assembly_reuse_key(
        output_path=output_path,
        canonical_input_lock=lock,
        render_profile=render_profile,
        projection_hash=projection_hash,
        render_contract_hash=contract_hash,
        policy_hash=policy_hash,
    )
    reusable = _reusable_assembly_materialization(
        directory,
        reuse_key=reuse_key,
        output_path=output_path,
    )
    if reusable is not None:
        return reusable

    rendered, actual_output = _render_assembly_output(
        render_port=render_port or TimelineRenderAdapter(),
        projection_path=projection_path,
        output_path=output_path,
        render_profile=render_profile,
        render_contract=render_contract,
    )
    lineage = build_picture_lineage(
        cmap_revision=revisions["cmap"],
        tracks_revision=revisions["tracks"],
        canonical_input_lock=lock,
        projection_hash=projection_hash,
        output=actual_output,
        render_contract=render_contract,
    )
    materialization_id = f"assembly-{render_hash[:12]}-{actual_output['sha256'][:12]}"
    target = directory / f"{materialization_id}.json"
    invariant = _assembly_invariant(
        materialization_id=materialization_id,
        lock=lock,
        projection_hash=projection_hash,
        render_profile=render_profile,
        render_contract=render_contract,
        contract_hash=contract_hash,
        render_hash=render_hash,
        lineage=lineage,
        policy=delivery_fidelity_policy,
        policy_hash=policy_hash,
        output=actual_output,
        producer=rendered.get("producer"),
    )
    record = _persist_assembly_record(target, invariant, clock=now_iso)
    _remember_reusable_assembly(
        directory,
        reuse_key=reuse_key,
        record_path=target,
    )
    return record
