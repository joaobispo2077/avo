#!/usr/bin/env python3
"""Failing vulture dead-code gate for src/avo (task-014 / FR-8).

Enforces vulture findings at ``min_confidence`` 60 (unused function/class/
method/variable signal). Known false positives (dynamic adapters, CLI/MCP
entrypoints, Protocol surfaces) must appear in
``scripts/ci/deadcode-allowlist.json`` with a reason. New unexpected dead code
fails CI; warn-only mode is intentionally absent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from vulture import Vulture

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = Path(__file__).resolve().parent / "deadcode-allowlist.json"
TARGET = ROOT / "src" / "avo"
DEFAULT_MIN_CONFIDENCE = 60


def _norm_repo_path(path: str | Path) -> str:
    text = Path(path).as_posix().replace("\\", "/")
    if "src/avo/" in text:
        return "src/avo/" + text.split("src/avo/", 1)[1]
    p = Path(path)
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return text


def _load_allowlist() -> tuple[int, dict[tuple[str, str], dict]]:
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    min_confidence = int(raw.get("min_confidence", DEFAULT_MIN_CONFIDENCE))
    if min_confidence != DEFAULT_MIN_CONFIDENCE:
        raise SystemExit(
            f"allowlist min_confidence must be {DEFAULT_MIN_CONFIDENCE}, "
            f"got {min_confidence}"
        )
    index: dict[tuple[str, str], dict] = {}
    for entry in raw.get("items", []):
        path = str(entry["path"]).replace("\\", "/")
        name = str(entry["name"])
        key = (path, name)
        if key in index:
            raise SystemExit(f"duplicate allowlist entry: {path}::{name}")
        if not entry.get("reason"):
            raise SystemExit(f"allowlist entry missing reason: {path}::{name}")
        index[key] = entry
    return min_confidence, index


def _collect_findings(
    min_confidence: int,
) -> list[tuple[str, str, str, int, int, str]]:
    vulture = Vulture(verbose=False)
    vulture.scavenge([str(TARGET)])
    out: list[tuple[str, str, str, int, int, str]] = []
    for item in vulture.get_unused_code(min_confidence=min_confidence):
        rel = _norm_repo_path(item.filename)
        out.append(
            (
                rel,
                str(item.name),
                str(item.typ),
                int(item.first_lineno),
                int(item.confidence),
                str(item.message),
            )
        )
    return out


def main() -> int:
    min_confidence, allowlist = _load_allowlist()
    findings = _collect_findings(min_confidence)

    violations: list[str] = []
    seen: set[tuple[str, str]] = set()

    for path, name, _kind, lineno, confidence, message in findings:
        key = (path, name)
        if key in allowlist:
            seen.add(key)
            continue
        violations.append(
            f"{path}:{lineno} {message} ({confidence}% confidence)"
        )

    stale = sorted(set(allowlist) - seen)
    stale_msgs = [
        f"{path}::{name} allowlisted but no longer reported by vulture "
        f"— remove from deadcode-allowlist.json"
        for path, name in stale
    ]

    try:
        allowlist_disp = ALLOWLIST_PATH.relative_to(ROOT).as_posix()
    except ValueError:
        allowlist_disp = ALLOWLIST_PATH.as_posix()
    print(
        f"==> quality:deadcode (vulture min-confidence {min_confidence} on src/avo)"
    )
    print(f"    allowlist: {allowlist_disp}")
    print(f"    allowlisted items: {len(allowlist)}")
    print(f"    current findings: {len(findings)}")

    failed = False
    if violations:
        failed = True
        print("NEW dead-code findings (not allowlisted):", file=sys.stderr)
        for line in violations:
            print(f"  ERROR: {line}", file=sys.stderr)
    if stale_msgs:
        failed = True
        print("Stale allowlist entries:", file=sys.stderr)
        for line in stale_msgs:
            print(f"  ERROR: {line}", file=sys.stderr)

    if failed:
        return 1

    print("quality:deadcode passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
