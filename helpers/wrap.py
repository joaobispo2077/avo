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

try:
    import avo_state
except ImportError:  # pragma: no cover
    from . import avo_state  # type: ignore

try:
    from project_inventory import InventoryReport, build_inventory_report
except ImportError:
    try:
        from .project_inventory import InventoryReport, build_inventory_report  # type: ignore
    except ImportError:
        InventoryReport = Any  # type: ignore
        build_inventory_report = None  # type: ignore

try:
    from session import final_session_id, load_session_meta
except ImportError:
    try:
        from .session import final_session_id, load_session_meta  # type: ignore
    except ImportError:
        final_session_id = None  # type: ignore
        load_session_meta = None  # type: ignore

try:
    from stats import load_stats_config
except ImportError:
    try:
        from .stats import load_stats_config  # type: ignore
    except ImportError:
        load_stats_config = None  # type: ignore

SCHEMA_VERSION = 1
DRAFT_JSON = "avo.wrap.draft.json"
DRAFT_MD = "avo.wrap.draft.md"
FINAL_JSON = "avo.wrap.json"
FINAL_MD = "avo.wrap.md"


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

    deleted_on_cleanup: list[dict[str, Any]] = []
    if status == "final":
        if added_then_removed:
            deleted_on_cleanup = [
                {"path": _entry_path(entry), "bytes": _entry_bytes(entry)}
                for entry in added_then_removed
            ]
        elif scheduled:
            deleted_on_cleanup = [
                {"path": _entry_path(entry), "bytes": _entry_bytes(entry)}
                for entry in scheduled
            ]
        if freed_bytes is None:
            freed_bytes = int(space.get("deleteCandidateBytes", 0))

    sample_limit = 50
    if load_stats_config is not None:
        sample_limit = load_stats_config().deleted_path_sample_limit

    deleted_sample, deleted_count = truncate_path_list(
        deleted_on_cleanup if status == "final" else scheduled,
        max_items=sample_limit,
    )

    raw_dir = Path(str(inv.get("rawDir", ".")))
    editlog = "EDITLOG.md" if (raw_dir / "EDITLOG.md").is_file() else None

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
            "scheduledForDeletion": scheduled,
            "preserved": preserved,
            "addedThenRemoved": added_then_removed,
            "modified": modified,
            "deletedOnCleanup": deleted_on_cleanup if status == "final" else [],
            "deletedCount": deleted_count if status == "final" else len(scheduled),
            "deletedSample": [
                _entry_path(entry) for entry in deleted_sample
            ],
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
    return payload


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

    try:
        from telemetry import human_bytes
    except ImportError:
        from .telemetry import human_bytes  # type: ignore

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

    scheduled = files.get("scheduledForDeletion") or []
    if status == "draft" and scheduled:
        lines.append("## Scheduled for deletion")
        lines.append("")
        for entry in scheduled[:20]:
            path = _entry_path(entry)
            size = _entry_bytes(entry)
            lines.append(f"- `{path}` ({human_bytes(size)})")
        if len(scheduled) > 20:
            lines.append(f"- … and {len(scheduled) - 20} more")
        lines.append("")

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


def _write_sidecar(raw_dir: Path, json_name: str, md_name: str, payload: dict[str, Any]) -> tuple[Path, Path]:
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


def _resolve_session_id(raw_dir: Path, master_basename: str, session_id: str | None) -> str:
    if session_id:
        return session_id
    if final_session_id is not None:
        return final_session_id(raw_dir, master_basename)
    raise ValueError("session_id required when session helpers unavailable")


def _resolve_provider(raw_dir: Path, session_id: str | None) -> tuple[str, str]:
    title = ""
    provider = "unknown"
    if session_id and load_session_meta is not None:
        try:
            meta = load_session_meta(session_id)
            provider = str(meta.get("provider") or provider)
            title = str(meta.get("title") or "")
        except FileNotFoundError:
            pass
    project_path = raw_dir / "avo.project.json"
    if project_path.is_file():
        try:
            project = json.loads(project_path.read_text(encoding="utf-8"))
            provider = str(project.get("provider") or provider)
            title = str(project.get("title") or title)
        except (OSError, ValueError):
            pass
    return provider, title


def _cmd_draft(args: argparse.Namespace) -> int:
    if build_inventory_report is None:
        print("error: project_inventory unavailable", file=sys.stderr)
        return 1
    raw_dir = Path(args.raw_dir)
    summary = Path(args.summary_file).read_text(encoding="utf-8")
    session_id = _resolve_session_id(raw_dir, args.master_basename, args.session_id)
    provider, title = _resolve_provider(raw_dir, args.session_id)
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
    print(f"draft wrap: {md_path}")
    print(f"draft json: {json_path}")
    return 0


def _cmd_final(args: argparse.Namespace) -> int:
    if build_inventory_report is None:
        print("error: project_inventory unavailable", file=sys.stderr)
        return 1
    raw_dir = Path(args.raw_dir)
    summary = Path(args.summary_file).read_text(encoding="utf-8")
    session_id = _resolve_session_id(raw_dir, args.master_basename, args.session_id)
    provider, title = _resolve_provider(raw_dir, args.session_id)
    if args.title:
        title = args.title

    report = build_inventory_report(
        raw_dir,
        args.master_basename,
        pre_json_path=args.pre,
    )
    inv = report.to_dict()
    freed = args.freed_bytes
    if freed is None:
        freed = int((inv.get("space") or {}).get("deleteCandidateBytes", 0))

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
        freed_bytes=freed,
    )
    json_path, md_path = write_wrap_final(raw_dir, payload)
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
    parent.add_argument("--pre", type=Path, default=None, help="Path to pre.json baseline.")
    parent.add_argument("--learning-note", default="")
    parent.add_argument(
        "--ai-memory",
        default="skipped",
        choices=("filed", "skipped"),
        help="ai-memory learndown status.",
    )

    p_draft = sub.add_parser("draft", parents=[parent], help="Write draft wrap sidecars.")
    p_draft.set_defaults(func=_cmd_draft)

    p_final = sub.add_parser("final", parents=[parent], help="Write final wrap sidecars.")
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
