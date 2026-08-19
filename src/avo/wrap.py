"""Wrap report generation for AVO pipeline metrics — draft and final sidecars.

Local-only: no network I/O. Artifacts live on the footage volume as
``<rawDir>/avo.wrap.draft.*`` and ``<rawDir>/avo.wrap.*``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from avo import avo_state
from avo.project_inventory import InventoryReport, build_inventory_report, load_project
from avo.session import final_session_id, load_session_meta
from avo.stats import load_stats_config

SCHEMA_VERSION = 1
DRAFT_JSON = "avo.wrap.draft.json"
DRAFT_MD = "avo.wrap.draft.md"
FINAL_JSON = "avo.wrap.json"
FINAL_MD = "avo.wrap.md"


def _load_wrap_draft(raw_dir: Path) -> dict[str, Any] | None:
    path = Path(raw_dir) / DRAFT_JSON
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _scratch_meta_for_session(session_id: str) -> tuple[str | None, str | None]:
    if not session_id:
        return None, None
    try:
        from avo.avo_state import state_dir

        root = state_dir() / "tmp"
        meta = root / "learndown" / session_id / "inventory.meta.json"
        report = root / "learndown" / session_id / "inventory.report.json"
    except Exception:
        return None, None
    scratch_meta = str(meta) if meta.is_file() else None
    scratch_report = str(report) if report.is_file() else None
    return scratch_meta, scratch_report


def resolve_wrap_raw_dir(raw_dir: Path) -> Path:
    """Map WSL ``/mnt/<letter>/`` on Windows; parent-fallback only with project file."""
    from avo.timeline.workspace import resolve_project_raw_dir

    raw_dir = Path(raw_dir)
    project_file = raw_dir / "avo.project.json"
    project_path = project_file if project_file.is_file() else None
    return resolve_project_raw_dir(project_path, raw_dir)


def truncate_path_list(
    paths: list[Any],
    *,
    max_items: int | None = None,
) -> tuple[list[Any], int]:
    """Return ``(sample, total_count)`` capped at ``max_items``."""
    total = len(paths)
    limit = max_items
    if limit is None:
        if load_stats_config is not None:
            limit = load_stats_config().deleted_path_sample_limit
        else:
            limit = 50
    if total <= limit:
        return list(paths), total
    return list(paths[:limit]), total


def _inventory_dict(inventory: InventoryReport | dict[str, Any]) -> dict[str, Any]:
    if isinstance(inventory, dict):
        return inventory
    return inventory.to_dict()


def _entry_path(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("path", ""))
    return str(getattr(entry, "path", ""))


def _entry_bytes(entry: Any) -> int:
    if isinstance(entry, dict):
        return int(entry.get("bytes", entry.get("size", 0)))
    return int(getattr(entry, "bytes", getattr(entry, "size", 0)))


def _entries_as_path_bytes(entries: list[Any]) -> list[dict[str, Any]]:
    return [
        {"path": _entry_path(entry), "bytes": _entry_bytes(entry)} for entry in entries
    ]


def _deleted_on_cleanup_entries(
    *,
    status: str,
    scheduled: list[Any],
    added_then_removed: list[Any],
) -> list[dict[str, Any]]:
    if status != "final":
        return []
    if added_then_removed:
        return _entries_as_path_bytes(added_then_removed)
    if scheduled:
        return _entries_as_path_bytes(scheduled)
    return []


def _copy_draft_deletes(
    draft: dict[str, Any], sample_limit: int
) -> tuple[list[Any], list[Any], int]:
    draft_files = draft.get("files") or {}
    deleted_on_cleanup = list(
        draft_files.get("deletedOnCleanup")
        or draft_files.get("scheduledForDeletion")
        or []
    )
    sample, total = truncate_path_list(deleted_on_cleanup, max_items=sample_limit)
    return deleted_on_cleanup, sample, total


def _inherit_draft_space(
    *,
    status: str,
    raw_dir: Path,
    space: dict[str, Any],
    freed_bytes: int | None,
    deleted_on_cleanup: list[Any],
    sample_limit: int,
) -> tuple[int | None, int | None, list[Any], list[Any], int]:
    deleted_cleanup_sample, deleted_cleanup_total = truncate_path_list(
        deleted_on_cleanup, max_items=sample_limit
    )
    if status != "final" or freed_bytes is not None:
        return (
            freed_bytes,
            None,
            deleted_on_cleanup,
            deleted_cleanup_sample,
            deleted_cleanup_total,
        )
    current_bytes = int(space.get("deleteCandidateBytes", 0))
    draft = _load_wrap_draft(raw_dir)
    if current_bytes != 0 or draft is None:
        return (
            current_bytes,
            None,
            deleted_on_cleanup,
            deleted_cleanup_sample,
            deleted_cleanup_total,
        )
    draft_space = draft.get("space") or {}
    inherited_count = int((draft.get("files") or {}).get("deletedCount", 0))
    if not deleted_on_cleanup:
        deleted_on_cleanup, deleted_cleanup_sample, deleted_cleanup_total = (
            _copy_draft_deletes(draft, sample_limit)
        )
    return (
        int(draft_space.get("deleteCandidateBytes", 0)),
        inherited_count,
        deleted_on_cleanup,
        deleted_cleanup_sample,
        deleted_cleanup_total,
    )


def build_wrap_payload(
    inventory: InventoryReport | dict[str, Any],
    *,
    session_id: str,
    provider: str,
    master_basename: str,
    summary: str,
    status: str,
    title: str = "",
    learning_note: str = "",
    ai_memory: str = "skipped",
    freed_bytes: int | None = None,
) -> dict[str, Any]:
    """Build wrap JSON payload from inventory report and session metadata."""
    inv = _inventory_dict(inventory)
    space = inv.get("space") or {}
    files = inv.get("files") or {}

    scheduled = list(files.get("scheduledForDeletion") or [])
    preserved = list(files.get("preserved") or [])
    added_then_removed = list(files.get("addedThenRemoved") or [])
    modified = list(files.get("modified") or [])
    degraded = bool(files.get("degradedMode", False))

    sample_limit = 50
    if load_stats_config is not None:
        sample_limit = load_stats_config().deleted_path_sample_limit

    scheduled_sample, scheduled_total = truncate_path_list(
        scheduled, max_items=sample_limit
    )
    added_sample, _added_total = truncate_path_list(
        added_then_removed, max_items=sample_limit
    )
    modified_sample, _modified_total = truncate_path_list(
        modified, max_items=sample_limit
    )

    deleted_on_cleanup = _deleted_on_cleanup_entries(
        status=status,
        scheduled=scheduled,
        added_then_removed=added_then_removed,
    )
    raw_dir = Path(str(inv.get("rawDir", ".")))
    (
        freed_bytes,
        inherited_count,
        deleted_on_cleanup,
        deleted_cleanup_sample,
        deleted_cleanup_total,
    ) = _inherit_draft_space(
        status=status,
        raw_dir=raw_dir,
        space=space,
        freed_bytes=freed_bytes,
        deleted_on_cleanup=deleted_on_cleanup,
        sample_limit=sample_limit,
    )

    sample_source = deleted_cleanup_sample if status == "final" else scheduled_sample
    deleted_count = scheduled_total
    if status == "final":
        deleted_count = (
            inherited_count if inherited_count is not None else deleted_cleanup_total
        )

    editlog = "EDITLOG.md" if (raw_dir / "EDITLOG.md").is_file() else None
    scratch_meta, _scratch_report = _scratch_meta_for_session(session_id)

    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "sessionId": session_id,
        "rawDir": str(raw_dir.resolve()),
        "provider": provider,
        "title": title,
        "masterBasename": master_basename,
        "generatedAt": avo_state.now_iso(),
        "summary": summary,
        "space": {
            "preCleanupProjectBytes": int(space.get("preCleanupProjectBytes", 0)),
            "deleteCandidateBytes": int(space.get("deleteCandidateBytes", 0)),
            "preservedBytes": int(space.get("preservedBytes", 0)),
            "freedBytes": freed_bytes if status == "final" else None,
        },
        "files": {
            "scheduledForDeletion": scheduled_sample,
            "preserved": preserved,
            "addedThenRemoved": added_sample,
            "modified": modified_sample,
            "deletedOnCleanup": deleted_cleanup_sample if status == "final" else [],
            "deletedCount": deleted_count,
            "deletedSample": [_entry_path(entry) for entry in sample_source],
            "degradedMode": degraded,
        },
        "learning": {
            "aiMemory": ai_memory,
            "note": learning_note,
        },
        "links": {
            "editlog": editlog,
        },
    }
    if scratch_meta:
        payload["files"]["scratchMeta"] = scratch_meta
        payload["links"]["scratchMeta"] = scratch_meta
    return payload


def _append_scheduled_for_deletion(
    lines: list[str], files: dict[str, Any], *, status: str
) -> None:
    from avo.telemetry import human_bytes

    scheduled = files.get("scheduledForDeletion") or []
    if status != "draft" or not scheduled:
        return
    scheduled_total = int(files.get("deletedCount") or len(scheduled))
    lines.append("## Scheduled for deletion")
    lines.append("")
    shown = scheduled[:20]
    for entry in shown:
        lines.append(f"- `{_entry_path(entry)}` ({human_bytes(_entry_bytes(entry))})")
    if scheduled_total > len(shown):
        lines.append(f"- … and {scheduled_total - len(shown)} more")
    lines.append("")


def render_markdown(payload: dict[str, Any]) -> str:
    """Render deterministic markdown from wrap JSON payload."""
    status = payload.get("status", "draft")
    title = payload.get("title") or payload.get("masterBasename", "Untitled")
    provider = payload.get("provider", "unknown")
    master = payload.get("masterBasename", "")
    summary = payload.get("summary", "").strip()
    space = payload.get("space") or {}
    files = payload.get("files") or {}
    learning = payload.get("learning") or {}
    links = payload.get("links") or {}

    from avo.telemetry import human_bytes

    lines: list[str] = []
    heading = "AVO Wrap (final)" if status == "final" else "AVO Wrap (draft preview)"
    lines.append(f"# {heading}")
    lines.append("")
    lines.append(f"- **Provider:** {provider}")
    lines.append(f"- **Title:** {title}")
    lines.append(f"- **Master:** `{master}`")
    lines.append(f"- **Session:** `{payload.get('sessionId', '')}`")
    lines.append(f"- **Generated:** {payload.get('generatedAt', '')}")
    if files.get("degradedMode"):
        lines.append("- **Inventory mode:** degraded (no pre.json baseline)")
    lines.append("")

    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")

    lines.append("## Space")
    lines.append("")
    lines.append(
        f"- Pre-cleanup project: **{human_bytes(space.get('preCleanupProjectBytes', 0))}**"
    )
    lines.append(
        f"- Scheduled for deletion: **{human_bytes(space.get('deleteCandidateBytes', 0))}**"
    )
    lines.append(f"- Preserved set: **{human_bytes(space.get('preservedBytes', 0))}**")
    if status == "final" and space.get("freedBytes") is not None:
        lines.append(f"- Freed on cleanup: **{human_bytes(space['freedBytes'])}**")
    lines.append("")

    _append_scheduled_for_deletion(lines, files, status=status)

    preserved = files.get("preserved") or []
    if preserved:
        lines.append("## Preserved artifacts")
        lines.append("")
        for entry in preserved:
            path = _entry_path(entry)
            size = _entry_bytes(entry)
            lines.append(f"- `{path}` ({human_bytes(size)})")
        lines.append("")

    if status == "final":
        deleted = files.get("deletedOnCleanup") or []
        if deleted:
            lines.append("## Deleted on cleanup")
            lines.append("")
            count = files.get("deletedCount", len(deleted))
            lines.append(f"**{count}** file(s) removed.")
            sample = files.get("deletedSample") or []
            for path in sample[:20]:
                lines.append(f"- `{path}`")
            if count > len(sample):
                lines.append(f"- … sample shows {len(sample)} of {count}")
            lines.append("")

    note = learning.get("note") or ""
    ai_mem = learning.get("aiMemory") or "skipped"
    lines.append("## Learning")
    lines.append("")
    lines.append(f"- ai-memory: **{ai_mem}**")
    if note:
        lines.append(f"- {note}")
    lines.append("")

    editlog = links.get("editlog")
    if editlog:
        lines.append(f"See also: [{editlog}]({editlog})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _write_sidecar(
    raw_dir: Path, json_name: str, md_name: str, payload: dict[str, Any]
) -> tuple[Path, Path]:
    raw_dir = raw_dir.resolve()
    json_path = raw_dir / json_name
    md_path = raw_dir / md_name
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return json_path, md_path


def write_wrap_draft(raw_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    """Write ``avo.wrap.draft.json`` and ``avo.wrap.draft.md``."""
    return _write_sidecar(raw_dir, DRAFT_JSON, DRAFT_MD, payload)


def write_wrap_final(raw_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    """Write ``avo.wrap.json`` and ``avo.wrap.md`` (draft sidecars retained)."""
    return _write_sidecar(raw_dir, FINAL_JSON, FINAL_MD, payload)


def _resolve_session_id(
    raw_dir: Path, master_basename: str, session_id: str | None
) -> str:
    if session_id:
        return session_id
    if final_session_id is not None:
        return final_session_id(raw_dir, master_basename)
    raise ValueError("session_id required when session helpers unavailable")


def _resolve_provider(
    raw_dir: Path,
    session_id: str | None,
    *,
    override: str = "",
) -> tuple[str, str]:
    title = ""
    provider = "unknown"
    if override.strip():
        provider = override.strip()
    project_path = raw_dir / "avo.project.json"
    if project_path.is_file():
        try:
            project = load_project(raw_dir)
            provider = str(project.get("provider") or provider)
            title = str(project.get("title") or "")
        except (OSError, ValueError):
            pass
    if provider == "unknown" and session_id and load_session_meta is not None:
        try:
            meta = load_session_meta(session_id)
            provider = str(meta.get("provider") or provider)
            title = str(meta.get("title") or title)
        except FileNotFoundError:
            pass
    return provider, title


def _cmd_draft(args: argparse.Namespace) -> int:
    if build_inventory_report is None:
        print("error: project_inventory unavailable", file=sys.stderr)
        return 1
    raw_dir = resolve_wrap_raw_dir(Path(args.raw_dir))
    summary = Path(args.summary_file).read_text(encoding="utf-8")
    session_id = _resolve_session_id(raw_dir, args.master_basename, args.session_id)
    provider, title = _resolve_provider(
        raw_dir, session_id, override=args.provider or ""
    )
    if args.title:
        title = args.title

    report = build_inventory_report(
        raw_dir,
        args.master_basename,
        pre_json_path=args.pre,
    )
    payload = build_wrap_payload(
        report,
        session_id=session_id,
        provider=provider,
        master_basename=args.master_basename,
        summary=summary,
        status="draft",
        title=title,
        learning_note=args.learning_note,
        ai_memory=args.ai_memory,
    )
    json_path, md_path = write_wrap_draft(raw_dir, payload)
    if not args.no_export:
        from avo.learndown_export import export_provider_learndown

        export_provider_learndown(payload)
    print(f"draft wrap: {md_path}")
    print(f"draft json: {json_path}")
    return 0


def _cmd_final(args: argparse.Namespace) -> int:
    if build_inventory_report is None:
        print("error: project_inventory unavailable", file=sys.stderr)
        return 1
    raw_dir = resolve_wrap_raw_dir(Path(args.raw_dir))
    summary = Path(args.summary_file).read_text(encoding="utf-8")
    session_id = _resolve_session_id(raw_dir, args.master_basename, args.session_id)
    provider, title = _resolve_provider(
        raw_dir, session_id, override=args.provider or ""
    )
    if args.title:
        title = args.title

    report = build_inventory_report(
        raw_dir,
        args.master_basename,
        pre_json_path=args.pre,
    )
    payload = build_wrap_payload(
        report,
        session_id=session_id,
        provider=provider,
        master_basename=args.master_basename,
        summary=summary,
        status="final",
        title=title,
        learning_note=args.learning_note,
        ai_memory=args.ai_memory,
        freed_bytes=args.freed_bytes,
    )
    json_path, md_path = write_wrap_final(raw_dir, payload)
    if not args.no_export:
        from avo.learndown_export import export_provider_learndown

        export_provider_learndown(payload)
    print(f"final wrap: {md_path}")
    print(f"final json: {json_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--raw-dir", type=Path, required=True)
    parent.add_argument("--master-basename", required=True)
    parent.add_argument("--summary-file", type=Path, required=True)
    parent.add_argument("--session-id", default=None)
    parent.add_argument("--title", default="")
    parent.add_argument(
        "--pre", type=Path, default=None, help="Path to pre.json baseline."
    )
    parent.add_argument("--learning-note", default="")
    parent.add_argument(
        "--provider",
        default="",
        help="Override provider slug (defaults to avo.project.json).",
    )
    parent.add_argument(
        "--no-export",
        action="store_true",
        help="Skip provider learndown export.",
    )
    parent.add_argument(
        "--ai-memory",
        default="skipped",
        choices=("filed", "skipped"),
        help="ai-memory learndown status.",
    )

    p_draft = sub.add_parser(
        "draft", parents=[parent], help="Write draft wrap sidecars."
    )
    p_draft.set_defaults(func=_cmd_draft)

    p_final = sub.add_parser(
        "final", parents=[parent], help="Write final wrap sidecars."
    )
    p_final.add_argument(
        "--freed-bytes",
        type=int,
        default=None,
        help="Actual bytes freed (defaults to delete candidate bytes).",
    )
    p_final.set_defaults(func=_cmd_final)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
