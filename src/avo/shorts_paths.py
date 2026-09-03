"""Canonical, cross-platform path resolution for Shorts batch workflows."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from avo.shorts_contract import atomic_write_json

_BATCH_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ShortsPathError(ValueError):
    """Raised before work when a Shorts path is ambiguous or escapes its root."""


@dataclass(frozen=True)
class ShortsBatchPaths:
    raw_dir: Path
    batch_id: str
    batch_root: Path
    root_source: str
    index_path: Path
    request_root: Path
    plans_dir: Path
    status_path: Path
    approvals_dir: Path
    work_dir: Path
    delivery_dir: Path
    masters_dir: Path
    transcripts_dir: Path

    def payload(self) -> dict[str, str]:
        values = asdict(self)
        return {
            "rawDir": str(values.pop("raw_dir")),
            "batchId": values.pop("batch_id"),
            "batchRoot": str(values.pop("batch_root")),
            "batchRootSource": values.pop("root_source"),
            **{
                {
                    "index_path": "indexPath",
                    "request_root": "requestRoot",
                    "plans_dir": "plansDir",
                    "status_path": "statusPath",
                    "approvals_dir": "approvalsDir",
                    "work_dir": "workDir",
                    "delivery_dir": "deliveryDir",
                    "masters_dir": "mastersDir",
                    "transcripts_dir": "transcriptsDir",
                }[key]: str(value)
                for key, value in values.items()
            },
        }

    def validate_plan_path(self, plan_path: Path | str, *, plan_version: str) -> Path:
        resolved = Path(plan_path).expanduser().resolve()
        if plan_version == "1.1":
            _require_contained(resolved, self.plans_dir, "v1.1 plan")
        return resolved


def _require_contained(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ShortsPathError(f"{label} must remain inside {root}") from exc


def _resolve_declared_batch_root(shorts_root: Path, batch_dir: Path | str) -> Path:
    declared = Path(batch_dir).expanduser()
    if declared.is_absolute():
        return declared.resolve()
    # Windows-style separators in relative overrides must resolve the same on
    # every platform (campaign\batch-one == campaign/batch-one).
    parts = [part for part in re.split(r"[\\/]+", str(batch_dir).strip()) if part]
    return (shorts_root / Path(*parts)).resolve()


def resolve_shorts_batch_paths(
    raw_dir: Path | str,
    batch_id: str,
    *,
    batch_dir: Path | str | None = None,
    legacy_output: Path | str | None = None,
) -> ShortsBatchPaths:
    raw = Path(raw_dir).expanduser().resolve()
    if not raw.is_dir():
        raise ShortsPathError(f"rawDir does not exist: {raw}")
    if not _BATCH_ID.fullmatch(batch_id):
        raise ShortsPathError("batchId must be lowercase kebab-case")
    shorts_root = (raw / "edit" / "shorts").resolve()
    source = "canonical-default"
    if batch_dir is not None:
        batch_root = _resolve_declared_batch_root(shorts_root, batch_dir)
        source = "invocation"
    elif legacy_output is not None:
        legacy = Path(legacy_output).expanduser().resolve()
        candidate = legacy if legacy.name == batch_id else legacy.parent
        if candidate.name == batch_id:
            batch_root = candidate
            source = "legacy-output"
        else:
            batch_root = shorts_root / batch_id
    else:
        batch_root = shorts_root / batch_id
    _require_contained(batch_root, shorts_root, "batchRoot")
    if batch_root.name != batch_id:
        raise ShortsPathError(
            f"batchRoot leaf {batch_root.name!r} must match batchId {batch_id!r}"
        )
    plans = batch_root / "plans"
    delivery = batch_root / "delivery"
    return ShortsBatchPaths(
        raw_dir=raw,
        batch_id=batch_id,
        batch_root=batch_root,
        root_source=source,
        index_path=shorts_root / "shorts.index.json",
        request_root=batch_root,
        plans_dir=plans,
        status_path=plans / "shorts.status.json",
        approvals_dir=batch_root / "approvals",
        work_dir=batch_root / "work",
        delivery_dir=delivery,
        masters_dir=delivery / "masters",
        transcripts_dir=delivery / "transcripts",
    )


def register_batch(
    paths: ShortsBatchPaths, *, plan_hash: str | None = None
) -> dict[str, Any]:
    """Atomically register one root/plan identity and reject collisions."""
    if paths.index_path.is_file():
        try:
            index = json.loads(paths.index_path.read_text(encoding="utf-8"))
            from avo import shorts_contract

            shorts_contract.validate_document(index, "index")
        except (OSError, ValueError) as exc:
            raise ShortsPathError(f"invalid Shorts index: {paths.index_path}") from exc
    else:
        index = {"schemaVersion": "1.0.0", "batches": []}
    batches = list(index.get("batches") or [])
    existing = next(
        (entry for entry in batches if entry.get("batchId") == paths.batch_id), None
    )
    entry = {
        "batchId": paths.batch_id,
        "batchRoot": str(paths.batch_root),
        "batchRootSource": paths.root_source,
        "planHash": plan_hash,
    }
    if existing and Path(str(existing.get("batchRoot"))).resolve() != paths.batch_root:
        raise ShortsPathError(
            f"batchId {paths.batch_id!r} is already registered at {existing.get('batchRoot')}"
        )
    if existing:
        entry["planHash"] = plan_hash or existing.get("planHash")
        batches[batches.index(existing)] = entry
    else:
        batches.append(entry)
    index = {
        "schemaVersion": "1.0.0",
        "batches": sorted(batches, key=lambda row: row["batchId"]),
    }
    from avo import shorts_contract

    shorts_contract.validate_document(index, "index")
    atomic_write_json(paths.index_path, index)
    return index


def snapshot_external_file(
    source: Path | str,
    target: Path | str,
    *,
    expected_hash: str | None = None,
) -> dict[str, str]:
    """Copy an external request/approval once and bind it to immutable bytes."""
    source_path = Path(source).resolve()
    target_path = Path(target).resolve()
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if expected_hash and digest != expected_hash:
        raise ShortsPathError("external snapshot hash does not match expectation")
    if target_path.exists():
        existing = hashlib.sha256(target_path.read_bytes()).hexdigest()
        if existing != digest:
            raise ShortsPathError(f"immutable snapshot collision: {target_path}")
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
    return {"path": str(target_path), "sha256": digest}
