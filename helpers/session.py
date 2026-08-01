"""Session lifecycle for AVO pipeline metrics — provisional id, pre-inventory, finalize.

Local-only: no network I/O. Session snapshots live under `.avo/sessions/<id>/`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import avo_state


@dataclass
class SessionContext:
    id: str
    raw_dir: Path
    provider: str
    started_at: str
    master_basename: str | None = None


@dataclass
class FileEntry:
    path: str
    size: int


@dataclass
class FileDiff:
    added: list[FileEntry]
    removed: list[FileEntry]
    modified: list[FileEntry]
    unchanged: list[FileEntry]


def normalize_path(path: Path) -> str:
    """Resolve path and normalize for stable cross-platform hashing."""
    resolved = Path(path).expanduser().resolve()
    text = resolved.as_posix()
    if sys.platform == "win32":
        text = text.casefold()
    return text


def _session_hash(*parts: str) -> str:
    payload = "".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def provisional_session_id(raw_dir: Path, started_at: str) -> str:
    return _session_hash(normalize_path(raw_dir), started_at)


def final_session_id(raw_dir: Path, master_basename: str) -> str:
    return _session_hash(normalize_path(raw_dir), master_basename)


def session_dir(session_id: str) -> Path:
    return avo_state.sessions_dir() / session_id


def scan_inventory(root: Path, *, relative_to: Path | None = None) -> dict[str, int]:
    """Return {relative_posix_path: size_bytes} for all regular files under root."""
    root = Path(root).expanduser().resolve()
    base = Path(relative_to).expanduser().resolve() if relative_to else root
    inventory: dict[str, int] = {}
    if not root.is_dir():
        return inventory
    for path in root.rglob("*"):
        try:
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(base).as_posix()
            inventory[rel] = path.stat().st_size
        except (OSError, ValueError):
            continue
    return inventory


def diff_inventories(pre: dict[str, int], post: dict[str, int]) -> FileDiff:
    """Classify file changes using size-only comparison."""
    pre_keys = set(pre)
    post_keys = set(post)
    added = sorted(
        (FileEntry(path=p, size=post[p]) for p in post_keys - pre_keys),
        key=lambda e: e.path,
    )
    removed = sorted(
        (FileEntry(path=p, size=pre[p]) for p in pre_keys - post_keys),
        key=lambda e: e.path,
    )
    modified: list[FileEntry] = []
    unchanged: list[FileEntry] = []
    for path in sorted(pre_keys & post_keys):
        pre_size = pre[path]
        post_size = post[path]
        entry = FileEntry(path=path, size=post_size)
        if pre_size != post_size:
            modified.append(entry)
        else:
            unchanged.append(entry)
    return FileDiff(added=added, removed=removed, modified=modified, unchanged=unchanged)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_session_meta(session_id: str) -> dict[str, Any]:
    meta_path = session_dir(session_id) / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"session meta not found: {meta_path}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def start_session(raw_dir: Path, provider: str, title: str = "") -> SessionContext:
    raw_dir = Path(raw_dir).expanduser().resolve()
    started_at = avo_state.now_iso()
    session_id = provisional_session_id(raw_dir, started_at)
    sdir = session_dir(session_id)
    sdir.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {
        "id": session_id,
        "rawDir": str(raw_dir),
        "provider": provider,
        "startedAt": started_at,
        "masterBasename": None,
    }
    if title:
        meta["title"] = title

    pre_payload = {
        "scannedAt": started_at,
        "files": scan_inventory(raw_dir, relative_to=raw_dir),
    }

    _write_json(sdir / "meta.json", meta)
    _write_json(sdir / "pre.json", pre_payload)

    return SessionContext(
        id=session_id,
        raw_dir=raw_dir,
        provider=provider,
        started_at=started_at,
    )


def finalize_session(session_id: str, master_basename: str) -> SessionContext:
    meta = load_session_meta(session_id)
    raw_dir = Path(meta["rawDir"])
    final_id = final_session_id(raw_dir, master_basename)

    src = session_dir(session_id)
    dst = session_dir(final_id)

    meta["masterBasename"] = master_basename
    meta["id"] = final_id

    if session_id != final_id:
        if not src.is_dir():
            raise FileNotFoundError(f"session directory not found: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            raise FileExistsError(f"final session directory already exists: {dst}")
        src.rename(dst)
        target = dst
    else:
        target = src

    _write_json(target / "meta.json", meta)

    return SessionContext(
        id=final_id,
        raw_dir=raw_dir,
        provider=str(meta["provider"]),
        started_at=str(meta["startedAt"]),
        master_basename=master_basename,
    )


def _context_to_dict(ctx: SessionContext) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": ctx.id,
        "rawDir": str(ctx.raw_dir),
        "provider": ctx.provider,
        "startedAt": ctx.started_at,
        "masterBasename": ctx.master_basename,
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AVO pipeline session lifecycle (local-only).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="Begin session and write pre-inventory snapshot.")
    p_start.add_argument("--raw-dir", required=True, help="Footage workflow root (rawDir).")
    p_start.add_argument("--provider", required=True, help="Provider slug.")
    p_start.add_argument("--title", default="", help="Optional working title.")

    p_finalize = sub.add_parser("finalize", help="Set master basename and compute final session id.")
    p_finalize.add_argument("--session-id", required=True, help="Provisional session id from start.")
    p_finalize.add_argument("--master-basename", required=True, help="Approved master file stem.")

    args = parser.parse_args(argv)

    if args.cmd == "start":
        ctx = start_session(Path(args.raw_dir), args.provider, title=args.title)
        sys.stdout.write(json.dumps(_context_to_dict(ctx), indent=2, ensure_ascii=False) + "\n")
        return 0

    if args.cmd == "finalize":
        try:
            ctx = finalize_session(args.session_id, args.master_basename)
        except (FileNotFoundError, FileExistsError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        sys.stdout.write(json.dumps(_context_to_dict(ctx), indent=2, ensure_ascii=False) + "\n")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
