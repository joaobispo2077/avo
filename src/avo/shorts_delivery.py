"""Immutable promotion and delivery recording for Shorts batches."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from avo import final_transcript_artifacts, shorts_contract, shorts_media


class DeliveryError(RuntimeError):
    """Promotion is blocked by missing evidence or immutable output collision."""


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


def promote_batch(
    plan: Mapping[str, Any],
    status: dict[str, Any],
    delivery_dir: Path,
    *,
    transcript_generator: Callable[..., Mapping[str, Path]] | None = None,
) -> dict[str, Any]:
    ensure_promotable(status)
    generator = transcript_generator or final_transcript_artifacts.generate_from_master
    delivery_dir.mkdir(parents=True, exist_ok=True)
    masters = delivery_dir / "masters"
    transcripts = delivery_dir / "transcripts"
    masters.mkdir(exist_ok=True)
    transcripts.mkdir(exist_ok=True)
    rows = []
    plan_items = {item["id"]: item for item in plan["items"]}
    for item_status in status["items"]:
        short_id = item_status["shortId"]
        revision = int(item_status.get("masterRevision", 0)) + 1
        master = (
            masters
            / f"{plan_items[short_id]['expectedOutputBasename']}-master-v{revision:03d}.mp4"
        )
        if master.exists():
            raise DeliveryError(f"immutable master already exists: {master}")
        proof = next(
            (
                Path(a["path"])
                for a in reversed(item_status["artifacts"])
                if a["kind"] == "proof"
            ),
            None,
        )
        if proof is None or not proof.is_file():
            raise DeliveryError(f"Short {short_id} has no readable proof")
        shutil.copy2(proof, master)
        sidecars = generator(master, transcripts)
        fingerprint = shorts_media.sha256_file(master)
        transcript_rows = []
        for kind, path in sidecars.items():
            path = Path(path)
            transcript_rows.append(
                {
                    "kind": kind,
                    "path": str(path),
                    "hash": shorts_media.sha256_file(path),
                }
            )
            item_status["artifacts"].append(
                {
                    "kind": "transcript",
                    "path": str(path),
                    "hash": shorts_media.sha256_file(path),
                    "revision": revision,
                }
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
        rows.append(
            {
                "shortId": short_id,
                "masterPath": str(master),
                "sha256": fingerprint,
                "masterRevision": revision,
                "sourcePlanHash": plan["planHash"],
                "transcripts": transcript_rows,
            }
        )
    manifest = {
        "version": "1.0",
        "batchId": plan["batchId"],
        "planHash": plan["planHash"],
        "items": rows,
    }
    manifest_path = shorts_contract.atomic_write_json(
        delivery_dir / "delivery-manifest.json", manifest
    )
    (delivery_dir / "EDITLOG.md").write_text(
        "# Shorts delivery edit log\n\nGenerated from the immutable batch plan; generated compositions were not hand edited.\n",
        encoding="utf-8",
    )
    (delivery_dir / "SOURCE-LOG.md").write_text(
        "# Shorts delivery source log\n\n"
        + "\n".join(f"- {item['id']}: {item['sourceRange']}" for item in plan["items"])
        + "\n",
        encoding="utf-8",
    )
    status["batchState"] = "delivered"
    status["deliveryComplete"] = True
    return {"status": status, "manifest": manifest, "manifestPath": manifest_path}
