"""Shared read/write for AVO runtime state (.avo/state.json).

`.avo/` is gitignored. State holds only non-secret runtime data:
version, last update check timestamp, chosen transcription language, rolling
telemetry stats, and optional per-video session history for `/avo.stats`.
Used by setup, telemetry, stats, session helpers, and the update checker.

Cross-platform: pathlib only, no hardcoded separators.
"""

from __future__ import annotations

from avo.paths import repo_root
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any




def state_dir() -> Path:
    return repo_root() / ".avo"


def state_path() -> Path:
    return state_dir() / "state.json"


def sessions_dir() -> Path:
    """Per-pipeline session snapshots (.avo/sessions/<id>/). Gitignored via .avo/."""
    path = state_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def package_version() -> str:
    pkg = repo_root() / "package.json"
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
        return str(data.get("version") or "0.0.0")
    except (OSError, ValueError):
        return "0.0.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_state() -> dict[str, Any]:
    return {
        "version": package_version(),
        "lastUpdateCheck": None,
        "transcription": {},
        "stats": {},
    }


def load_state() -> dict[str, Any]:
    path = state_path()
    if not path.is_file():
        return default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default_state()
    base = default_state()
    base.update(data if isinstance(data, dict) else {})
    return base


def save_state_atomic(state: dict[str, Any]) -> Path:
    """Write state atomically (temp file + replace) to avoid corruption on crash."""
    state_dir().mkdir(parents=True, exist_ok=True)
    path = state_path()
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
    return path


def save_state(state: dict[str, Any]) -> Path:
    return save_state_atomic(state)


def update_state(**changes: Any) -> dict[str, Any]:
    state = load_state()
    for key, value in changes.items():
        state[key] = value
    save_state(state)
    return state


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def update_age_days(state: dict[str, Any] | None = None) -> float | None:
    """Days since lastUpdateCheck, or None if never checked / unparseable."""
    state = state or load_state()
    last = _parse_iso(state.get("lastUpdateCheck"))
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() / 86400.0


def is_update_due(days: float = 7.0, state: dict[str, Any] | None = None) -> bool:
    age = update_age_days(state)
    return age is None or age >= days


def _get_path(state: dict[str, Any], dotted: str) -> Any:
    node: Any = state
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set_path(state: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = state
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def _coerce(value: str) -> Any:
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read/write AVO runtime state (.avo/state.json).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get", help="Print a dotted key (or whole state).")
    p_get.add_argument("key", nargs="?", default="")

    p_set = sub.add_parser("set", help="Set a dotted key to a value.")
    p_set.add_argument("key")
    p_set.add_argument("value")

    p_init = sub.add_parser("init", help="Ensure state exists; optionally stamp version/language.")
    p_init.add_argument("--version", default="")
    p_init.add_argument("--language", default="")
    p_init.add_argument("--whisper-model", default="", help="Persist faster-whisper model size (catalog id).")
    p_init.add_argument("--touch-update", action="store_true",
                        help="Set lastUpdateCheck to now.")

    p_due = sub.add_parser("due", help="Print 'due' or 'recent' based on lastUpdateCheck age.")
    p_due.add_argument("--days", type=float, default=7.0)

    p_touch = sub.add_parser("touch-update", help="Set lastUpdateCheck to now.")

    args = parser.parse_args(argv)

    if args.cmd == "get":
        state = load_state()
        if not args.key:
            sys.stdout.write(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        else:
            value = _get_path(state, args.key)
            sys.stdout.write(("" if value is None else str(value)) + "\n")
        return 0

    if args.cmd == "set":
        state = load_state()
        _set_path(state, args.key, _coerce(args.value))
        save_state(state)
        return 0

    if args.cmd == "init":
        state = load_state()
        if args.version:
            state["version"] = args.version
        if args.language:
            state.setdefault("transcription", {})["language"] = args.language
        if args.whisper_model:
            state.setdefault("transcription", {})["model"] = args.whisper_model
            state.setdefault("models", {})["transcribe"] = args.whisper_model
        if args.touch_update:
            state["lastUpdateCheck"] = now_iso()
        save_state(state)
        sys.stdout.write(f"state ready: {state_path()}\n")
        return 0

    if args.cmd == "due":
        age = update_age_days()
        due = is_update_due(args.days)
        age_str = "never" if age is None else f"{age:.1f}d"
        sys.stdout.write(f"{'due' if due else 'recent'} {age_str}\n")
        return 0

    if args.cmd == "touch-update":
        state = load_state()
        state["lastUpdateCheck"] = now_iso()
        save_state(state)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
