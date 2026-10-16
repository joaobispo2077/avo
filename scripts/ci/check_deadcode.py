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
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from vulture import Vulture

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = Path(__file__).resolve().parent / "deadcode-allowlist.json"
TARGET = ROOT / "src" / "avo"
DEFAULT_MIN_CONFIDENCE = 60
REPORT_PATH = ROOT / "reports" / "quality" / "deadcode.json"


def _write_report(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _report() -> dict:
    return {
        "schema_version": 1,
        "gate": "deadcode",
        "sha": os.environ.get("AVO_QUALITY_SHA") or os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("AVO_QUALITY_RUN_ID")
        or os.environ.get("GITHUB_RUN_ID"),
        "recorded_at": datetime.now(UTC).isoformat(),
        "status": "ERROR",
        "complete": False,
        "policy": {
            "scope": "src/avo",
            "min_confidence": DEFAULT_MIN_CONFIDENCE,
            "allowlist_path": _norm_repo_path(ALLOWLIST_PATH),
        },
        "findings": [],
        "allowlisted": [],
        "violations": [],
        "stale": [],
        "errors": [],
        "counts": None,
    }


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
    if vulture.exit_code not in (0, 3):
        raise ValueError(
            f"vulture could not analyze all source files (exit {vulture.exit_code})"
        )
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


def _check(report: dict) -> int:
    min_confidence, allowlist = _load_allowlist()
    report["policy"]["configured_allowlist_entries"] = len(allowlist)
    findings = _collect_findings(min_confidence)

    violations: list[str] = []
    seen: set[tuple[str, str]] = set()

    for path, name, kind, lineno, confidence, message in findings:
        key = (path, name)
        finding = {
            "path": path,
            "name": name,
            "line": lineno,
            "kind": kind,
            "confidence": confidence,
            "message": message,
            "disposition": "unwaived",
        }
        report["findings"].append(finding)
        if key in allowlist:
            seen.add(key)
            finding.update(disposition="allowlisted", reason=allowlist[key]["reason"])
            report["allowlisted"].append(finding)
            continue
        report["violations"].append(finding)
        violations.append(f"{path}:{lineno} {message} ({confidence}% confidence)")

    stale = sorted(set(allowlist) - seen)
    report["stale"] = [allowlist[key] for key in stale]
    stale_msgs = [
        f"{path}::{name} allowlisted but no longer reported by vulture "
        f"— remove from deadcode-allowlist.json"
        for path, name in stale
    ]

    try:
        allowlist_disp = ALLOWLIST_PATH.relative_to(ROOT).as_posix()
    except ValueError:
        allowlist_disp = ALLOWLIST_PATH.as_posix()
    print(f"==> quality:deadcode (vulture min-confidence {min_confidence} on src/avo)")
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

    report["complete"] = True
    report["status"] = "FAIL" if failed else "PASS"
    report["counts"] = {
        "findings": len(report["findings"]),
        "allowlisted": len(report["allowlisted"]),
        "unwaived": len(report["violations"]),
        "stale": len(report["stale"]),
        "errors": 0,
    }
    if failed:
        return 1

    print("quality:deadcode passed.")
    return 0


def main() -> int:
    report = _report()
    try:
        return _check(report)
    except (OSError, ValueError, TypeError, KeyError, SystemExit) as exc:
        report["errors"].append({"message": str(exc)})
        print(f"quality:deadcode failed: {exc}", file=sys.stderr)
        return 1
    finally:
        _write_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
