"""Export provider-scoped learndown entries under providers/<slug>/learndowns/."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from avo import avo_state
from avo.paths import providers_dir, repo_root
from avo.project_inventory import load_project

SCHEMA_VERSION = 1
INDEX_NAME = "index.json"
LEARNDOWN_JSON = "learndown.json"
LEARNDOWN_MD = "learndown.md"
WRAP_DRAFT_JSON = "wrap.draft.json"
WRAP_DRAFT_MD = "wrap.draft.md"
WRAP_FINAL_JSON = "wrap.json"
WRAP_FINAL_MD = "wrap.md"


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def build_entry_id(
    master_basename: str,
    *,
    title: str = "",
    generated_at: str = "",
) -> str:
    """Build ``YYYYMMDD-topic-slug`` from master basename or title."""
    date_match = re.match(r"^(\d{8})", master_basename)
    date = date_match.group(1) if date_match else ""
    if not date and generated_at:
        date = generated_at[:10].replace("-", "")

    body = master_basename
    if date and body.startswith(date):
        body = body[len(date) :].lstrip("-")
    body = re.sub(r"-master-.*$", "", body)
    if not body:
        body = _slugify(title or master_basename)
    body = _slugify(body) or "untitled"
    return f"{date}-{body}" if date else body


def provider_learndowns_dir(provider: str, *, root: Path | None = None) -> Path:
    return (root or repo_root()) / "providers" / provider / "learndowns"


def build_learndown_payload(wrap_payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(wrap_payload.get("provider") or "").strip()
    master = str(wrap_payload.get("masterBasename") or "")
    generated_at = str(wrap_payload.get("generatedAt") or avo_state.now_iso())
    entry_id = build_entry_id(
        master,
        title=str(wrap_payload.get("title") or ""),
        generated_at=generated_at,
    )
    learning = dict(wrap_payload.get("learning") or {})
    ai_memory = str(learning.get("aiMemory") or "skipped")
    if ai_memory == "skipped":
        ai_memory = "exported"

    raw_dir = Path(str(wrap_payload.get("rawDir") or "."))
    space = wrap_payload.get("space") or {}
    status = str(wrap_payload.get("status") or "draft")

    wrap_paths = {
        "draftJson": str((raw_dir / "avo.wrap.draft.json").resolve()),
        "draftMd": str((raw_dir / "avo.wrap.draft.md").resolve()),
        "finalJson": str((raw_dir / "avo.wrap.json").resolve()),
        "finalMd": str((raw_dir / "avo.wrap.md").resolve()),
    }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "entryId": entry_id,
        "provider": provider,
        "masterBasename": master,
        "rawDir": str(raw_dir.resolve()),
        "title": str(wrap_payload.get("title") or ""),
        "status": status,
        "generatedAt": generated_at,
        "sessionId": str(wrap_payload.get("sessionId") or ""),
        "summary": str(wrap_payload.get("summary") or ""),
        "space": {
            "preCleanupProjectBytes": int(space.get("preCleanupProjectBytes", 0)),
            "deleteCandidateBytes": int(space.get("deleteCandidateBytes", 0)),
            "preservedBytes": int(space.get("preservedBytes", 0)),
            "freedBytes": space.get("freedBytes"),
        },
        "learning": {
            "aiMemory": ai_memory,
            "note": str(learning.get("note") or ""),
        },
        "wrapPaths": wrap_paths,
    }


def render_learndown_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Provider learndown — {payload.get('entryId', '')}",
        "",
        f"- **Provider:** {payload.get('provider', '')}",
        f"- **Master:** `{payload.get('masterBasename', '')}`",
        f"- **Status:** {payload.get('status', '')}",
        f"- **Generated:** {payload.get('generatedAt', '')}",
        f"- **Raw dir:** `{payload.get('rawDir', '')}`",
        "",
    ]
    summary = str(payload.get("summary") or "").strip()
    if summary:
        lines.extend(["## Summary", "", summary, ""])
    learning = payload.get("learning") or {}
    note = str(learning.get("note") or "").strip()
    if note:
        lines.extend(["## Learning note", "", note, ""])
    return "\n".join(lines).rstrip() + "\n"


def _load_index(index_path: Path, provider: str) -> dict[str, Any]:
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provider": provider,
        "updatedAt": avo_state.now_iso(),
        "entries": [],
    }


def _upsert_index_entry(index: dict[str, Any], payload: dict[str, Any]) -> None:
    entries = list(index.get("entries") or [])
    entry = {
        "entryId": payload["entryId"],
        "masterBasename": payload["masterBasename"],
        "rawDir": payload["rawDir"],
        "title": payload.get("title") or "",
        "status": payload["status"],
        "generatedAt": payload["generatedAt"],
    }
    entries = [e for e in entries if e.get("entryId") != entry["entryId"]]
    entries.append(entry)
    entries.sort(key=lambda e: (e.get("generatedAt", ""), e.get("entryId", "")))
    index["entries"] = entries
    index["updatedAt"] = avo_state.now_iso()
    index["provider"] = payload["provider"]


def _copy_if_exists(source: Path, dest: Path) -> None:
    if source.is_file():
        shutil.copy2(source, dest)


def export_provider_learndown(
    wrap_payload: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path | None:
    """Write provider learndown entry. Returns entry dir or None when skipped."""
    payload = build_learndown_payload(wrap_payload)
    provider = payload["provider"]
    if not provider or provider == "unknown":
        print(
            f"learndown export skipped: unknown provider for {payload['masterBasename']}",
            file=sys.stderr,
        )
        return None

    base = provider_learndowns_dir(provider, root=root)
    entry_dir = base / payload["entryId"]
    entry_dir.mkdir(parents=True, exist_ok=True)

    (entry_dir / LEARNDOWN_JSON).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (entry_dir / LEARNDOWN_MD).write_text(
        render_learndown_markdown(payload),
        encoding="utf-8",
    )

    raw_dir = Path(payload["rawDir"])
    status = payload["status"]
    _copy_if_exists(raw_dir / "avo.wrap.draft.json", entry_dir / WRAP_DRAFT_JSON)
    _copy_if_exists(raw_dir / "avo.wrap.draft.md", entry_dir / WRAP_DRAFT_MD)
    if status == "final":
        _copy_if_exists(raw_dir / "avo.wrap.json", entry_dir / WRAP_FINAL_JSON)
        _copy_if_exists(raw_dir / "avo.wrap.md", entry_dir / WRAP_FINAL_MD)

    index_path = base / INDEX_NAME
    index = _load_index(index_path, provider)
    _upsert_index_entry(index, payload)
    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"provider learndown: {entry_dir}")
    return entry_dir


def _resolve_backfill_provider(
    payload: dict[str, Any],
    *,
    override: str = "",
) -> str:
    if override.strip():
        return override.strip()
    provider = str(payload.get("provider") or "").strip()
    if provider and provider != "unknown":
        return provider
    raw_dir = Path(str(payload.get("rawDir") or ""))
    project = load_project(raw_dir)
    resolved = str(project.get("provider") or "").strip()
    if resolved:
        return resolved
    return provider or "unknown"


def _cmd_backfill(args: argparse.Namespace) -> int:
    wrap_path = Path(args.wrap_json)
    payload = json.loads(wrap_path.read_text(encoding="utf-8"))
    provider = _resolve_backfill_provider(payload, override=args.provider or "")
    if provider and provider != str(payload.get("provider") or ""):
        payload = dict(payload)
        payload["provider"] = provider
    entry = export_provider_learndown(payload, root=args.root)
    return 0 if entry is not None else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_backfill = sub.add_parser("backfill", help="Export from an existing wrap JSON.")
    p_backfill.add_argument("--wrap-json", type=Path, required=True)
    p_backfill.add_argument("--root", type=Path, default=None)
    p_backfill.add_argument(
        "--provider",
        default="",
        help="Override provider slug (defaults to wrap JSON or avo.project.json).",
    )
    p_backfill.set_defaults(func=_cmd_backfill)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
