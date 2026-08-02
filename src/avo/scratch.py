"""Ephemeral scratch paths for learndown and inventory reports.

Scratch files live under ``.avo/tmp/learndown/<session-id>/`` and are removed
after successful ``project_inventory cleanup``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from avo.avo_state import tmp_dir

LEARNDOWN_SUBDIR = "learndown"
INVENTORY_REPORT_NAME = "inventory.report.json"
INVENTORY_META_NAME = "inventory.meta.json"


def learndown_scratch_dir(session_id: str) -> Path:
    path = tmp_dir() / LEARNDOWN_SUBDIR / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_inventory_scratch(
    session_id: str,
    report: dict[str, Any],
) -> tuple[Path, Path]:
    """Write full report + compact meta under the session scratch dir."""
    scratch = learndown_scratch_dir(session_id)
    report_path = scratch / INVENTORY_REPORT_NAME
    meta_path = scratch / INVENTORY_META_NAME
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    space = report.get("space") or {}
    meta = {
        "sessionId": session_id,
        "rawDir": report.get("rawDir"),
        "masterBasename": report.get("masterBasename"),
        "generatedAt": report.get("generatedAt"),
        "space": {
            "preCleanupProjectBytes": space.get("preCleanupProjectBytes", 0),
            "deleteCandidateBytes": space.get("deleteCandidateBytes", 0),
            "preservedBytes": space.get("preservedBytes", 0),
        },
        "scheduledForDeletionCount": len(
            (report.get("files") or {}).get("scheduledForDeletion") or []
        ),
        "preservedCount": len((report.get("files") or {}).get("preserved") or []),
    }
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report_path, meta_path


def purge_scratch(session_id: str) -> bool:
    """Delete the scratch directory for ``session_id``. Returns True if removed."""
    path = tmp_dir() / LEARNDOWN_SUBDIR / session_id
    if not path.exists():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def scratch_exists(session_id: str) -> bool:
    path = tmp_dir() / LEARNDOWN_SUBDIR / session_id
    return path.is_dir()
