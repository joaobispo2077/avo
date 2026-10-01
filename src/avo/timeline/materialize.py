"""Canonical materialization application services."""

from __future__ import annotations

from copy import deepcopy
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
    audiovisual_lineage: dict[str, Any],
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
        "audiovisualLineage": audiovisual_lineage,
        "audiovisualLineageHash": audiovisual_lineage["lineageHash"],
        "deliveryFidelityPolicy": policy,
        "deliveryFidelityPolicyHash": policy_hash,
        "output": output,
        "producer": producer or {"name": "timeline-render", "version": "unknown"},
    }


def _assembly_media_inputs(
    revisions: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cmap_snapshot = revisions["cmap"].get("snapshot") or {}
    originals = list(cmap_snapshot.get("sources") or [])
    contributors: list[dict[str, Any]] = []
    for source in originals:
        fingerprint = source.get("fingerprint") or {}
        contributors.append(
            {
                "nodeId": f"source-{source.get('sourceId', '')}",
                "kind": "source",
                "role": "base",
                "mediaClass": (
                    "camera-original"
                    if source.get("kind") == "raw"
                    else str(source.get("kind") or "source")
                ),
                "locator": str(
                    source.get("locator") or fingerprint.get("locator") or ""
                ),
                **fingerprint,
                "pictureCarrying": True,
                "audioCarrying": True,
            }
        )
    tracks = revisions["tracks"].get("snapshot") or {}
    for group, carrying in (
        ("videoTracks", {"pictureCarrying": True, "audioCarrying": False}),
        ("audioTracks", {"pictureCarrying": False, "audioCarrying": True}),
    ):
        for layer in (tracks.get(group) or {}).get("layers") or []:
            source = layer.get("source") or {}
            generator = layer.get("generator") or source.get("generator")
            locator = str(source.get("locator") or "")
            if not locator and not source.get("sha256") and not generator:
                continue
            provenance = layer.get("provenance") or {}
            contributors.append(
                {
                    "nodeId": f"track-{layer.get('layerId', '')}",
                    "kind": "generated" if generator and not locator else "source",
                    "role": str(layer.get("role") or "media"),
                    "mediaClass": str(
                        provenance.get("mediaClass")
                        or ("generated" if generator and not locator else "source")
                    ),
                    "locator": locator,
                    "assetId": str(
                        source.get("generatedAssetId")
                        or layer.get("generatedAssetId")
                        or ""
                    ),
                    **source,
                    **carrying,
                }
            )
    return contributors, originals


def _preflight_assembly_media(
    workspace: Any,
    revisions: dict[str, dict[str, Any]],
    admission: dict[str, Any] | None,
) -> None:
    from .media_admission import (
        require_media_admission,
        require_no_forbidden_outputs,
    )
    from .migration import inventory_historical_output_fingerprints

    contributors, cmap_originals = _assembly_media_inputs(revisions)
    configured = admission or {}
    known_outputs = [
        *(
            inventory_historical_output_fingerprints(workspace.raw_dir)
            if getattr(workspace, "raw_dir", None) is not None
            else []
        ),
        *(configured.get("knownOutputs") or []),
    ]
    require_no_forbidden_outputs(contributors, known_outputs=known_outputs)
    if admission is not None:
        require_media_admission(
            contributors,
            registered_originals=[
                *cmap_originals,
                *(configured.get("registeredOriginals") or []),
            ],
            generated_assets=configured.get("generatedAssets") or {},
            known_outputs=known_outputs,
        )


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
    media_admission: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render and immutably bind a complete canonical timeline assembly."""
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    from .contracts import content_hash
    from .lineage import validate_audiovisual_lineage
    from .picture_lineage import (
        build_audiovisual_lineage,
        build_picture_lineage,
        current_assembly_lock,
    )
    from .projection import write_assembly_projection
    from .store import now_iso

    lock, revisions = current_assembly_lock(workspace)
    _preflight_assembly_media(workspace, revisions, media_admission)
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
    audiovisual_lineage = build_audiovisual_lineage(
        cmap_revision=revisions["cmap"],
        tracks_revision=revisions["tracks"],
        canonical_input_lock=lock,
        projection_hash=projection_hash,
        output=actual_output,
        render_contract=render_contract,
        picture_lineage=lineage,
        generated_assets=(media_admission or {}).get("generatedAssets") or {},
    )
    validate_audiovisual_lineage(audiovisual_lineage)
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
        audiovisual_lineage=audiovisual_lineage,
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


class ProofMaterializationError(RuntimeError):
    def __init__(self, code: str, message: str, remediation: str) -> None:
        super().__init__(message)
        self.code = code
        self.remediation = remediation

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "remediation": self.remediation,
            "blocking": True,
        }


def canonical_proof_media_inputs(
    workspace: Any, proof_plan: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Resolve locked source IDs from canonical CMap/Tracks without proof media."""
    required = {
        key.removeprefix("source:")
        for key in proof_plan.get("canonicalInputLock") or {}
        if key.startswith("source:")
    }
    inputs: dict[str, dict[str, Any]] = {}
    cmap_index = workspace.require_active("cmap")
    cmap = workspace.store("cmap").revision(cmap_index["headRevisionId"])
    for source in (cmap.get("snapshot") or {}).get("sources") or []:
        source_id = str(source.get("sourceId") or "")
        if source_id not in required:
            continue
        fingerprint = source.get("fingerprint") or {}
        locator = source.get("locator") or fingerprint.get("locator")
        if locator:
            path = Path(str(locator))
            if not path.is_absolute():
                path = Path(workspace.raw_dir) / path
            inputs[source_id] = {
                "path": path,
                "mediaClass": str(source.get("mediaClass") or "source"),
                "ancestry": deepcopy(source.get("ancestry") or []),
            }
    tracks_index = workspace.require_active("tracks")
    tracks = workspace.store("tracks").revision(tracks_index["headRevisionId"])
    snapshot = tracks.get("snapshot") or {}
    for group in ("videoTracks", "audioTracks"):
        for layer in (snapshot.get(group) or {}).get("layers") or []:
            source = layer.get("source") or {}
            source_id = str(source.get("sourceId") or source.get("assetId") or "")
            if source_id not in required or source_id in inputs:
                continue
            locator = source.get("locator")
            if locator:
                path = Path(str(locator))
                if not path.is_absolute():
                    path = Path(workspace.raw_dir) / path
                inputs[source_id] = {
                    "path": path,
                    "mediaClass": str(
                        (layer.get("provenance") or {}).get("mediaClass") or "source"
                    ),
                    "ancestry": deepcopy(source.get("ancestry") or []),
                }
    return inputs


def _proof_plan_value(workspace: Any, proof_plan: dict[str, Any] | str | Path):
    from .proof_plan import ProofPlanCompiler

    compiler = ProofPlanCompiler(workspace)
    if isinstance(proof_plan, dict):
        value = proof_plan
        from .contracts import document_hash_excluding, validate_document

        if value.get("proofPlanHash") != document_hash_excluding(
            value, "proofPlanHash"
        ):
            raise ProofMaterializationError(
                "PROOF_PLAN_HASH_MISMATCH",
                "proof plan changed after compilation",
                "restore the immutable plan or compile a new one",
            )
        validate_document(value, "avo.proof-plan.schema.json")
        return compiler, value
    return compiler, compiler.load(proof_plan)


def _proof_readiness(render_port: Any, plan: dict[str, Any]) -> dict[str, bool]:
    if not hasattr(render_port, "proof_tool_readiness"):
        raise ProofMaterializationError(
            "PROOF_TOOL_READINESS_UNKNOWN",
            "proof renderer does not expose tool readiness",
            "use a registered proof renderer with a readiness probe",
        )
    result = render_port.proof_tool_readiness(plan)
    if not isinstance(result, dict):
        raise ProofMaterializationError(
            "PROOF_TOOL_READINESS_INVALID",
            "proof renderer returned invalid readiness evidence",
            "repair the renderer readiness adapter",
        )
    normalized = {str(key): bool(value) for key, value in result.items()}
    normalized.setdefault(
        "proof-plan-executor", hasattr(render_port, "render_proof_plan")
    )
    return normalized


def _proof_render(
    render_port: Any,
    plan: dict[str, Any],
    output: Path,
    *,
    window: dict[str, int] | None,
) -> dict[str, Any]:
    if not hasattr(render_port, "render_proof_plan"):
        raise ProofMaterializationError(
            "PROOF_RENDER_ADAPTER_UNAVAILABLE",
            "renderer cannot consume an immutable ProofPlan",
            "use the ProofPlan-aware timeline render adapter",
        )
    rendered = render_port.render_proof_plan(
        plan,
        Path(output),
        window=deepcopy(window),
    )
    if not Path(output).is_file():
        raise ProofMaterializationError(
            "PROOF_OUTPUT_MISSING",
            f"renderer did not create the declared output: {output}",
            "inspect the registered renderer failure and rerun this exact plan",
        )
    from .contracts import file_fingerprint

    actual = file_fingerprint(Path(output))
    declared = rendered.get("output") or {}
    if declared.get("sha256") != actual["sha256"]:
        raise ProofMaterializationError(
            "PROOF_OUTPUT_FINGERPRINT_MISMATCH",
            "renderer output identity differs from the produced bytes",
            "repair the renderer output record before review",
        )
    return {**rendered, "output": actual}


def render_proof_microproofs(
    *,
    workspace: Any,
    proof_plan: dict[str, Any] | str | Path,
    media_inputs: dict[str, Any],
    render_port: Any | None = None,
) -> dict[str, Any]:
    """Render every required risk window through the full proof's exact graph."""
    import json

    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    from .contracts import content_hash
    from .review_runner import select_microproof_windows
    from .store import write_immutable_json

    compiler, plan = _proof_plan_value(workspace, proof_plan)
    port = render_port or TimelineRenderAdapter()
    readiness = _proof_readiness(port, plan)
    preflight = compiler.require_preflight(
        plan,
        media_inputs=media_inputs,
        tool_readiness=readiness,
    )
    windows = select_microproof_windows(plan)
    directory = Path(workspace.timeline_dir) / "microproofs" / str(plan["proofPlanId"])
    suffix = Path(plan["output"]["path"]).suffix or ".mp4"
    results: list[dict[str, Any]] = []
    for index, window in enumerate(windows, 1):
        frame_range = {
            "startFrame": int(window["startFrame"]),
            "endFrameExclusive": int(window["endFrameExclusive"]),
        }
        output = directory / f"window-{index:04d}{suffix}"
        try:
            rendered = _proof_render(
                port,
                plan,
                output,
                window=frame_range,
            )
            status = str(rendered.get("status") or "pass")
            result = {
                "window": frame_range,
                "reasons": list(window["reasons"]),
                "operationIds": list(window["operationIds"]),
                "status": status,
                "output": rendered["output"],
                "graphHash": str(rendered.get("graphHash") or ""),
            }
        except Exception as exc:
            result = {
                "window": frame_range,
                "reasons": list(window["reasons"]),
                "operationIds": list(window["operationIds"]),
                "status": "fail",
                "error": str(exc),
            }
        results.append(result)
    gate = {
        "schemaVersion": "1.0.0",
        "proofPlanId": plan["proofPlanId"],
        "proofPlanHash": plan["proofPlanHash"],
        "preflightHash": preflight["reportHash"],
        "requiredWindows": [
            {
                "startFrame": item["startFrame"],
                "endFrameExclusive": item["endFrameExclusive"],
            }
            for item in windows
        ],
        "results": results,
        "status": (
            "pass"
            if results and all(item["status"] == "pass" for item in results)
            else "fail"
        ),
        "gateHash": "",
    }
    gate["gateHash"] = content_hash(
        {key: value for key, value in gate.items() if key != "gateHash"}
    )
    gate_path = directory / f"gate-{gate['gateHash'][:12]}.json"
    write_immutable_json(gate_path, gate)
    return {**json.loads(json.dumps(gate)), "path": str(gate_path)}


def _load_microproof_gate(value: dict[str, Any] | str | Path) -> dict[str, Any]:
    import json

    if isinstance(value, dict):
        return deepcopy(value)
    try:
        result = json.loads(Path(value).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProofMaterializationError(
            "PROOF_MICROPROOF_MISSING",
            f"cannot load required microproof gate: {exc}",
            "render and validate the plan's required microproof windows",
        ) from exc
    if not isinstance(result, dict):
        raise ProofMaterializationError(
            "PROOF_MICROPROOF_INVALID",
            "microproof gate must be a JSON object",
            "rerun microproof validation",
        )
    return result


def _require_current_microproof_gate(
    plan: dict[str, Any], gate: dict[str, Any], *, preflight_hash: str
) -> None:
    from .contracts import content_hash
    from .review_runner import select_microproof_windows

    expected_hash = content_hash(
        {key: value for key, value in gate.items() if key not in {"gateHash", "path"}}
    )
    if gate.get("gateHash") != expected_hash:
        raise ProofMaterializationError(
            "PROOF_MICROPROOF_HASH_MISMATCH",
            "microproof gate was modified after validation",
            "rerun microproof validation for this exact plan",
        )
    if (
        gate.get("proofPlanHash") != plan["proofPlanHash"]
        or gate.get("preflightHash") != preflight_hash
    ):
        raise ProofMaterializationError(
            "PROOF_MICROPROOF_STALE",
            "microproof evidence belongs to a different plan or preflight",
            "rerun microproofs from the current immutable plan",
        )
    required = [
        {
            "startFrame": item["startFrame"],
            "endFrameExclusive": item["endFrameExclusive"],
        }
        for item in select_microproof_windows(plan)
    ]
    if gate.get("requiredWindows") != required:
        raise ProofMaterializationError(
            "PROOF_MICROPROOF_INCOMPLETE",
            "microproof gate does not cover every required window",
            "rerun every changed-operation and historical-risk window",
        )
    statuses = [str(item.get("status")) for item in gate.get("results") or []]
    if any(
        status in {"needs-human", "needs-human-judgment", "ambiguous"}
        for status in statuses
    ):
        raise ProofMaterializationError(
            "PROOF_MICROPROOF_AMBIGUOUS",
            "required microproof evidence needs human judgment",
            "record the human disposition and rerun the gate",
        )
    if gate.get("status") != "pass" or len(statuses) != len(required):
        raise ProofMaterializationError(
            "PROOF_MICROPROOF_FAILED",
            "required microproof evidence is missing or failed",
            "repair the reported regressions and rerun microproof validation",
        )
    if any(status != "pass" for status in statuses):
        raise ProofMaterializationError(
            "PROOF_MICROPROOF_FAILED",
            "one or more required microproofs failed",
            "repair the defect and rerun the gate",
        )


def materialize_proof_plan(
    *,
    workspace: Any,
    proof_plan: dict[str, Any] | str | Path,
    microproof_gate: dict[str, Any] | str | Path,
    media_inputs: dict[str, Any],
    render_port: Any | None = None,
) -> dict[str, Any]:
    """Build a full candidate only after current required microproofs pass."""
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    from .contracts import content_hash
    from .store import now_iso, write_immutable_json

    compiler, plan = _proof_plan_value(workspace, proof_plan)
    port = render_port or TimelineRenderAdapter()
    readiness = _proof_readiness(port, plan)
    preflight = compiler.require_preflight(
        plan,
        media_inputs=media_inputs,
        tool_readiness=readiness,
    )
    gate = _load_microproof_gate(microproof_gate)
    _require_current_microproof_gate(
        plan,
        gate,
        preflight_hash=preflight["reportHash"],
    )
    output = Path(plan["output"]["path"])
    rendered = _proof_render(port, plan, output, window=None)
    record = {
        "schemaVersion": "1.0.0",
        "kind": "proof-plan",
        "materializationId": (
            f"proof-build-{plan['proofPlanHash'][:12]}-"
            f"{rendered['output']['sha256'][:12]}"
        ),
        "proofPlanId": plan["proofPlanId"],
        "proofPlanHash": plan["proofPlanHash"],
        "preflightHash": preflight["reportHash"],
        "microproofGateHash": gate["gateHash"],
        "canonicalInputLock": deepcopy(plan["canonicalInputLock"]),
        "renderProfile": plan["renderProfile"],
        "output": rendered["output"],
        "producer": deepcopy(rendered.get("producer") or {}),
        "createdAt": now_iso(),
        "materializationHash": "",
    }
    record["materializationHash"] = content_hash(
        {key: value for key, value in record.items() if key != "materializationHash"}
    )
    target = (
        Path(workspace.timeline_dir)
        / "materializations"
        / "proof-plan"
        / f"{record['materializationId']}.json"
    )
    write_immutable_json(target, record)
    return {**record, "path": str(target)}


def proof_build_status(
    *,
    workspace: Any,
    proof_plan: dict[str, Any] | str | Path,
    media_inputs: dict[str, Any],
    microproof_gate: dict[str, Any] | str | Path | None = None,
    render_port: Any | None = None,
) -> dict[str, Any]:
    """Return one non-mutating preflight/microproof build-gate summary."""
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    compiler, plan = _proof_plan_value(workspace, proof_plan)
    port = render_port or TimelineRenderAdapter()
    readiness = _proof_readiness(port, plan)
    preflight = compiler.preflight(
        plan,
        media_inputs=media_inputs,
        tool_readiness=readiness,
    )
    gate_state = "missing"
    gate_hash = None
    gate_error = None
    if microproof_gate is not None:
        try:
            gate = _load_microproof_gate(microproof_gate)
            _require_current_microproof_gate(
                plan,
                gate,
                preflight_hash=preflight["reportHash"],
            )
            gate_state = "pass"
            gate_hash = gate["gateHash"]
        except ProofMaterializationError as exc:
            gate_state = "blocked"
            gate_error = exc.to_dict()
    if preflight["status"] != "pass":
        status = "blocked"
    elif gate_state == "pass":
        status = "ready-for-full-build"
    elif gate_state == "missing":
        status = "ready-for-microproof"
    else:
        status = "blocked"
    return {
        "status": status,
        "proofPlanId": plan["proofPlanId"],
        "proofPlanHash": plan["proofPlanHash"],
        "preflight": preflight,
        "microproofGate": {
            "state": gate_state,
            "gateHash": gate_hash,
            "error": gate_error,
        },
    }
