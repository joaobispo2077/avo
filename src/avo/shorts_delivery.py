"""Immutable promotion and delivery recording for Shorts batches."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from avo import final_transcript_artifacts, shorts_contract, shorts_media, shorts_paths


class DeliveryError(RuntimeError):
    """Promotion or preservation is blocked by invalid immutable evidence."""


def _preserved_batch_paths(batch_root: Path) -> list[Path]:
    kept = _regular_files(batch_root.glob("shorts.request*.json"))
    plans = batch_root / "plans"
    if plans.is_dir():
        kept.extend(_regular_files(plans.glob("shorts.plan-*.json")))
        status = plans / "shorts.status.json"
        if status.is_file() and not status.is_symlink():
            kept.append(status)
    for preserved_root in (batch_root / "approvals", batch_root / "delivery"):
        if preserved_root.is_dir():
            kept.extend(_regular_files(preserved_root.rglob("*")))
    return kept


def _regular_files(paths: Any) -> list[Path]:
    return [path for path in paths if path.is_file() and not path.is_symlink()]


def _indexed_batch_roots(raw_dir: Path, index_path: Path) -> list[Path]:
    if not index_path.is_file():
        return []
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        shorts_contract.validate_document(index, "index")
        roots: list[Path] = []
        batch_ids: set[str] = set()
        for entry in index["batches"]:
            batch_id = entry["batchId"]
            if batch_id in batch_ids:
                raise shorts_paths.ShortsPathError(
                    f"duplicate batchId in Shorts index: {batch_id}"
                )
            batch_ids.add(batch_id)
            paths = shorts_paths.resolve_shorts_batch_paths(
                raw_dir,
                batch_id,
                batch_dir=entry["batchRoot"],
            )
            roots.append(paths.batch_root)
        return roots
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise DeliveryError(f"invalid Shorts index: {index_path}: {exc}") from exc


def preserved_shorts_paths(raw_dir: Path) -> list[Path]:
    """Return canonical Shorts records that reconstruction must retain.

    Proof trees, HyperFrames scratch, and prepared media stay deletable.
    """
    raw = Path(raw_dir).resolve()
    root = raw / "edit" / "shorts"
    if not root.is_dir():
        return []
    index_path = root / "shorts.index.json"
    kept: list[Path] = [index_path] if index_path.is_file() else []
    # The index is authoritative for supported nested roots. Direct children
    # remain discoverable for the documented v1.0 compatibility window.
    batch_roots = {
        *_indexed_batch_roots(raw, index_path),
        *(path.resolve() for path in root.iterdir() if path.is_dir()),
    }
    for batch_root in sorted(batch_roots):
        kept.extend(_preserved_batch_paths(batch_root))
    return sorted(set(kept))


def required_approval_gates(status: Mapping[str, Any]) -> list[str]:
    approved = {
        row["gate"]
        for row in status.get("batchApprovals") or []
        if row.get("status") in {"approved", "overridden"} and row.get("reference")
    }
    return [
        gate
        for gate in (
            "batch-plan",
            "motion-proof",
            "picture-lock",
            "rights",
            "pre-master",
        )
        if gate not in approved
    ]


def ensure_promotable(status: Mapping[str, Any]) -> None:
    if status.get("deliveryComplete") or status.get("batchState") == "delivered":
        raise DeliveryError(
            "batch is already delivered; create a new reviewed plan revision"
        )
    missing = required_approval_gates(status)
    if missing:
        raise DeliveryError(f"missing delivery approvals: {', '.join(missing)}")
    blocked = [
        item["shortId"]
        for item in status["items"]
        if item.get("dirty")
        or item.get("state") not in {"proof-approved", "master-qc"}
        or (item.get("qc") or {}).get("status") != "passed"
    ]
    if blocked:
        raise DeliveryError(
            f"items are not clean, approved, and QC-passed: {', '.join(blocked)}"
        )


def _artifact_by_kind(
    item_status: Mapping[str, Any], kind: str
) -> Mapping[str, Any] | None:
    return next(
        (
            artifact
            for artifact in reversed(item_status.get("artifacts") or [])
            if artifact.get("kind") == kind
        ),
        None,
    )


def _prepared_lineage_record(
    plan: Mapping[str, Any],
    plan_item: Mapping[str, Any],
    item_status: Mapping[str, Any],
) -> dict[str, Any] | None:
    artifact = _artifact_by_kind(item_status, "prepared-lineage")
    if artifact is None:
        if str(plan.get("version")) == "1.1":
            raise DeliveryError(
                f"Short {plan_item['id']} is missing canonical prepared lineage"
            )
        return None
    path = Path(str(artifact.get("path") or ""))
    if not path.is_file():
        raise DeliveryError(f"prepared lineage is unreadable: {path}")
    digest = shorts_media.sha256_file(path)
    if digest != artifact.get("hash"):
        raise DeliveryError(
            f"prepared lineage hash is stale for Short {plan_item['id']}"
        )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeliveryError(f"prepared lineage is invalid: {path}: {exc}") from exc
    expected = dict(record)
    lineage_hash = expected.pop("lineageHash", None)
    if lineage_hash != shorts_contract.content_hash(expected):
        raise DeliveryError(
            f"prepared lineage identity is stale for Short {plan_item['id']}"
        )
    if not _lineage_matches_plan(record, plan, plan_item):
        raise DeliveryError(
            f"prepared lineage does not match plan for Short {plan_item['id']}"
        )
    return {"recordSha256": digest, **record}


def _lineage_matches_plan(
    record: Mapping[str, Any],
    plan: Mapping[str, Any],
    plan_item: Mapping[str, Any],
) -> bool:
    return (
        record.get("planHash") == plan.get("planHash")
        and record.get("shortId") == plan_item.get("id")
        and record.get("sourceSegments") == plan_item.get("sourceSegments")
    )


def _insertion_lineage(
    request: Mapping[str, Any],
    plan_item: Mapping[str, Any],
    item_status: Mapping[str, Any],
) -> dict[str, Any] | None:
    resolved = plan_item.get("insertion")
    if not resolved:
        return None
    source = next(
        (
            row
            for row in request.get("insertions") or []
            if row.get("id") == resolved.get("id")
        ),
        {},
    )
    prepared = [
        dict(artifact)
        for artifact in item_status.get("artifacts") or []
        if artifact.get("kind")
        in {"prepared-insertion-video", "prepared-insertion-audio"}
    ]
    return {
        "id": resolved["id"],
        "sourcePath": source.get("sourcePath"),
        "sourceFingerprint": source.get("sourceFingerprint"),
        "videoStream": source.get("videoStream"),
        "audioStream": source.get("audioStream"),
        "sourceTimeMap": list(resolved.get("sourceTimeMap") or []),
        "rightsBasis": source.get("rightsBasis") or resolved.get("rightsReference"),
        "semanticApprovalReference": source.get("semanticApprovalReference"),
        "preparedArtifacts": prepared,
    }


def _release_evidence(request: Mapping[str, Any]) -> dict[str, Any]:
    diagnosis = dict(request.get("diagnosis") or {})
    delivery = dict((request.get("defaults") or {}).get("delivery") or {})
    return {
        "rights": _values(diagnosis, "rightsNotes")
        + _values(delivery, "rightsEvidence"),
        "disclosures": {
            "sponsorship": delivery.get("sponsorshipDisclosure"),
            "affiliate": delivery.get("affiliateDisclosure"),
            "reviewUnit": delivery.get("reviewUnitDisclosure"),
        },
        "privacy": _values(delivery, "privacyEvidence"),
        "safety": _values(delivery, "safetyEvidence"),
        "consent": _values(delivery, "consentEvidence"),
        "aiUse": _values(delivery, "aiUseEvidence"),
        "diagnosisNotes": _values(diagnosis, "privacySafetyDisclosureNotes"),
    }


def _values(source: Mapping[str, Any], key: str) -> list[Any]:
    value = source.get(key)
    return list(value) if value else []


def _declared_transformations(plan_item: Mapping[str, Any]) -> list[str]:
    transformations = ["trim"]
    if len(plan_item.get("sourceSegments") or []) > 1:
        transformations.append("concat")
    if float(plan_item.get("speed") or 1) != 1:
        transformations.append("speed")
    if plan_item.get("insertion"):
        transformations.append("composite")
    return transformations


def _load_plan_request(plan: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return shorts_contract.load_document(Path(plan["requestPath"]), "request")
    except (OSError, ValueError):
        return {}


def _transcript_generator(
    supplied: Callable[..., Mapping[str, Path]] | None,
) -> Callable[..., Mapping[str, Path]]:
    return supplied or final_transcript_artifacts.generate_from_master


def _transcript_rows(
    item_status: dict[str, Any],
    sidecars: Mapping[str, Path],
    revision: int,
) -> list[dict[str, Any]]:
    rows = []
    for kind, value in sidecars.items():
        path = Path(value)
        digest = shorts_media.sha256_file(path)
        rows.append({"kind": kind, "path": str(path), "hash": digest})
        item_status["artifacts"].append(
            {
                "kind": "transcript",
                "path": str(path),
                "hash": digest,
                "revision": revision,
            }
        )
    return rows


def _source_segments(
    plan: Mapping[str, Any], plan_item: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if plan_item.get("sourceSegments"):
        return list(plan_item["sourceSegments"])
    return [
        {
            "order": 1,
            "sourceId": str((plan.get("source") or {}).get("sourceId") or "master"),
            **dict(plan_item["sourceRange"]),
            "sourceFingerprint": plan.get("sourceFingerprint"),
            "evidenceReference": (plan_item.get("factualReviewReferences") or [None])[
                0
            ],
        }
    ]


def _promote_item(
    plan: Mapping[str, Any],
    plan_item: Mapping[str, Any],
    request: Mapping[str, Any],
    item_status: dict[str, Any],
    masters: Path,
    delivery_dir: Path,
    generator: Callable[..., Mapping[str, Path]],
) -> dict[str, Any]:
    short_id = item_status["shortId"]
    revision = int(item_status.get("masterRevision", 0)) + 1
    master = masters / (
        f"{plan_item['expectedOutputBasename']}-master-v{revision:03d}.mp4"
    )
    if master.exists():
        raise DeliveryError(f"immutable master already exists: {master}")
    proof_artifact = _artifact_by_kind(item_status, "proof")
    proof = Path(str((proof_artifact or {}).get("path") or ""))
    if not proof.is_file():
        raise DeliveryError(f"Short {short_id} has no readable proof")
    shutil.copy2(proof, master)
    transcript_rows = _transcript_rows(
        item_status, generator(master, delivery_dir), revision
    )
    fingerprint = shorts_media.sha256_file(master)
    if fingerprint != shorts_media.sha256_file(proof):
        raise DeliveryError(
            f"copied master bytes differ from proof for Short {short_id}"
        )
    item_status["artifacts"].append(
        {
            "kind": "master",
            "path": str(master),
            "hash": fingerprint,
            "revision": revision,
        }
    )
    item_status.update(
        {
            "state": "delivered",
            "masterRevision": revision,
            "dirty": False,
            "dirtyReasons": [],
        }
    )
    return {
        "shortId": short_id,
        "masterPath": str(master),
        "sha256": fingerprint,
        "masterRevision": revision,
        "sourcePlanHash": plan["planHash"],
        "sourceSegments": _source_segments(plan, plan_item),
        "preparedLineage": _prepared_lineage_record(plan, plan_item, item_status),
        "insertionLineage": _insertion_lineage(request, plan_item, item_status),
        "declaredTransformations": _declared_transformations(plan_item),
        "rightsReviewReferences": list(plan_item.get("rightsReviewReferences") or []),
        "factualReviewReferences": list(plan_item.get("factualReviewReferences") or []),
        "watchReview": item_status.get("watchReview"),
        "transcripts": transcript_rows,
    }


def _write_delivery_logs(
    delivery_dir: Path,
    manifest: Mapping[str, Any],
    plan_items: Mapping[str, Mapping[str, Any]],
) -> None:
    rows = manifest["items"]
    edit_rows = [
        (
            f"- {row['shortId']}: speed={plan_items[row['shortId']]['speed']}; "
            f"transformations={','.join(row['declaredTransformations'])}; "
            f"segments=`{json.dumps(row['sourceSegments'], ensure_ascii=False, sort_keys=True)}`"
        )
        for row in rows
    ]
    (delivery_dir / "EDITLOG.md").write_text(
        "# Shorts delivery edit log\n\n"
        "Generated from the immutable batch plan; generated compositions were "
        "not hand edited.\n\n## Ordered assembly\n\n" + "\n".join(edit_rows) + "\n",
        encoding="utf-8",
    )
    source_rows = [
        f"- {row['shortId']} base: `{json.dumps(row['sourceSegments'], ensure_ascii=False, sort_keys=True)}`\n"
        f"  insertion: `{json.dumps(row['insertionLineage'], ensure_ascii=False, sort_keys=True)}`\n"
        f"  prepared: `{json.dumps(row['preparedLineage'], ensure_ascii=False, sort_keys=True)}`"
        for row in rows
    ]
    (delivery_dir / "SOURCE-LOG.md").write_text(
        "# Shorts delivery source log\n\n"
        + "\n".join(source_rows)
        + "\n\n## Rights, disclosures, and approvals\n\n"
        + f"- Approvals: `{json.dumps(manifest['approvals'], ensure_ascii=False, sort_keys=True)}`\n"
        + f"- Release evidence: `{json.dumps(manifest['releaseEvidence'], ensure_ascii=False, sort_keys=True)}`\n",
        encoding="utf-8",
    )


def promote_batch(
    plan: Mapping[str, Any],
    status: dict[str, Any],
    delivery_dir: Path,
    *,
    transcript_generator: Callable[..., Mapping[str, Path]] | None = None,
    batch_paths: Any | None = None,
    approval_snapshot: Mapping[str, str] | None = None,
    legacy_external_delivery: str | None = None,
) -> dict[str, Any]:
    ensure_promotable(status)
    generator = _transcript_generator(transcript_generator)
    delivery_dir.mkdir(parents=True, exist_ok=True)
    masters = delivery_dir / "masters"
    transcripts = delivery_dir / "transcripts"
    masters.mkdir(exist_ok=True)
    transcripts.mkdir(exist_ok=True)
    plan_items = {item["id"]: item for item in plan["items"]}
    request = _load_plan_request(plan)
    rows = [
        _promote_item(
            plan,
            plan_items[item_status["shortId"]],
            request,
            item_status,
            masters,
            delivery_dir,
            generator,
        )
        for item_status in status["items"]
    ]
    manifest = {
        "version": str(plan.get("version") or "1.0"),
        "batchId": plan["batchId"],
        "planHash": plan["planHash"],
        "batchRoot": str(batch_paths.batch_root) if batch_paths else None,
        "batchRootSource": batch_paths.root_source if batch_paths else None,
        "legacyExternalDelivery": legacy_external_delivery,
        "requestPath": plan.get("requestPath"),
        "approvalSnapshot": dict(approval_snapshot or {}),
        "approvals": list(status.get("batchApprovals") or []),
        "requestContext": {
            "diagnosis": dict(request.get("diagnosis") or {}),
            "delivery": dict((request.get("defaults") or {}).get("delivery") or {}),
        },
        "releaseEvidence": _release_evidence(request),
        "items": rows,
    }
    manifest_path = shorts_contract.atomic_write_json(
        delivery_dir / "delivery-manifest.json", manifest
    )
    _write_delivery_logs(delivery_dir, manifest, plan_items)
    status["batchState"] = "delivered"
    status["deliveryComplete"] = True
    return {"status": status, "manifest": manifest, "manifestPath": manifest_path}
