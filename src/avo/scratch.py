"""Ephemeral scratch paths for learndown, QC, and session reports.

Scratch files live under ``.avo/tmp/<kind>/<session-id>/`` and are removed
after successful ``cleanup execute --session-id``. Never write repo-root
``.tmp-*`` files; use this module or ``<rawDir>/edit/``.
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
SCRATCH_KINDS = ("learndown", "qc", "shorts-proof", "session")
_REMEDIATION = "use avo.scratch.scratch_path or avo.avo_state.tmp_dir; never write repo-root .tmp-*"


class ScratchError(ValueError):
    """Raised when a scratch path would escape remembered roots."""


def _session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ScratchError(
            f"session_id is invalid: {session_id!r}. {_REMEDIATION}"
        )
    return value


def _kind(kind: str) -> str:
    value = str(kind or "").strip()
    if value not in SCRATCH_KINDS:
        raise ScratchError(
            f"unknown scratch kind {kind!r}; expected one of {SCRATCH_KINDS}. {_REMEDIATION}"
        )
    return value


def scratch_path(kind: str, session_id: str, *parts: str) -> Path:
    """Return a path under ``.avo/tmp/<kind>/<session-id>/``.

    Creates the session directory. Rejects unknown kinds, empty session ids,
    ``..`` segments, and absolute parts so writers cannot escape ``tmp_dir``.
    """
    root = tmp_dir().resolve()
    path = root / _kind(kind) / _session_id(session_id)
    for part in parts:
        fragment = Path(part)
        if fragment.is_absolute() or ".." in fragment.parts:
            raise ScratchError(
                f"scratch path part escapes tmp root: {part!r}. {_REMEDIATION}"
            )
        path = path / fragment
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ScratchError(
            f"scratch path escapes tmp root: {resolved}. {_REMEDIATION}"
        ) from exc
    if parts:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    else:
        resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def learndown_scratch_dir(session_id: str) -> Path:
    return scratch_path(LEARNDOWN_SUBDIR, session_id)


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


def purge_session_tmp(session_id: str) -> bool:
    """Delete every kind directory for ``session_id``. Returns True if anything removed."""
    session = _session_id(session_id)
    root = tmp_dir()
    removed = False
    for kind in SCRATCH_KINDS:
        path = root / kind / session
        if not path.exists():
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed = True
    return removed


def purge_scratch(session_id: str) -> bool:
    """Backward-compatible alias: purge all session tmp kinds."""
    try:
        return purge_session_tmp(session_id)
    except ScratchError:
        return False


def scratch_exists(session_id: str) -> bool:
    try:
        session = _session_id(session_id)
    except ScratchError:
        return False
    root = tmp_dir()
    return any((root / kind / session).is_dir() for kind in SCRATCH_KINDS)
