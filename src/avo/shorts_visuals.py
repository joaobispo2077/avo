"""Frozen, silent timed inserts shared by Shorts planning and render adapters."""

from __future__ import annotations

import hashlib
import math
import re
import shutil
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from avo.shorts_contract import ContractValidationError


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _validate_rect(rect: Mapping[str, Any]) -> None:
    x, y, width, height = (float(rect[k]) for k in ("x", "y", "width", "height"))
    if not all(math.isfinite(v) for v in (x, y, width, height)) or not (
        x >= 0
        and y >= 0
        and width > 0
        and height > 0
        and x + width <= 1 + 1e-9
        and y + height <= 1 + 1e-9
    ):
        raise ContractValidationError("visual insert rectangle must stay inside canvas")


def _validate_insert_ids(rows: Sequence[Mapping[str, Any]]) -> None:
    ids: set[str] = set()
    for row in rows:
        insert_id = str(row["id"])
        if insert_id in ids or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", insert_id):
            raise ContractValidationError(
                "visual insert IDs must be unique safe identifiers"
            )
        ids.add(insert_id)


def _validate_base_regions(rows: Sequence[Mapping[str, Any]]) -> None:
    regions: list[tuple[float, float]] = []
    for row in rows:
        start, end = float(row["startSec"]), float(row["endSec"])
        if row.get("baseRegion"):
            _validate_rect(row["baseRegion"])
            if any(
                start < prior_end and end > prior_start
                for prior_start, prior_end in regions
            ):
                raise ContractValidationError(
                    "visual insert baseRegion windows cannot overlap"
                )
            regions.append((start, end))


def _validate_original_path(path: Path, label: str) -> None:
    if re.search(
        r"(?:^|[/\\])(?:proofs?|previews?|masters?|delivery|renders)(?:[/\\]|$)",
        str(path),
        re.IGNORECASE,
    ) or re.search(
        r"(?:^|[-_])(?:proof|preview|master)(?:[-_.]|$)", path.name, re.IGNORECASE
    ):
        raise ContractValidationError(f"{label} prohibited derived media: {path}")


def _validate_insert_source(row: Mapping[str, Any]) -> None:
    path = Path(str(row["path"]))
    _validate_original_path(path, "visual insert")
    if not path.is_file() or _digest(path) != row["sha256"]:
        raise ContractValidationError(
            f"visual insert source fingerprint mismatch: {path}"
        )
    for ancestor in row.get("ancestry") or []:
        ancestor_path = Path(str(ancestor["locator"]))
        if (
            ancestor["mediaClass"] != "source"
            or not ancestor_path.is_file()
            or _digest(ancestor_path) != ancestor["sha256"]
        ):
            raise ContractValidationError(
                f"visual insert ancestry mismatch: {ancestor_path}"
            )


def _validate_insert_clock(row: Mapping[str, Any], duration: float) -> None:
    start, end = float(row["startSec"]), float(row["endSec"])
    if not (
        math.isfinite(start)
        and math.isfinite(end)
        and 0 <= start < end <= duration + 1e-6
    ):
        raise ContractValidationError(
            f"visual insert {row['id']} exceeds edited duration"
        )
    if row["kind"] != "video":
        return
    source_start = float(row["sourceStartSec"])
    source_end = float(row["sourceEndSec"])
    if (
        source_start < 0
        or not math.isfinite(source_end)
        or abs((source_end - source_start) - (end - start)) > 1e-6
    ):
        raise ContractValidationError(
            "visual insert video window must match edited duration without looping"
        )


def validate_visual_inserts(
    inserts: Sequence[Mapping[str, Any]], duration: float
) -> list[dict[str, Any]]:
    """Validate clocks, geometry and original source identity, returning frozen rows."""
    result = deepcopy(list(inserts))
    _validate_insert_ids(result)
    _validate_base_regions(result)
    for row in result:
        _validate_insert_clock(row, duration)
        _validate_rect(row["rect"])
        _validate_insert_source(row)
    return result


def prepare_visual_inserts(
    inserts: Sequence[Mapping[str, Any]], assets_dir: Path, *, duration: float
) -> list[dict[str, Any]]:
    """Copy verified source bytes under deterministic names; preserve source window."""
    rows = validate_visual_inserts(inserts, duration)
    assets_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        source = Path(row["path"])
        target = assets_dir / f"visual-{row['id']}{source.suffix.lower()}"
        shutil.copy2(source, target)
        if _digest(target) != row["sha256"]:
            raise ContractValidationError(
                f"visual insert changed while copying: {source}"
            )
        row["path"] = str(target)
    return rows
