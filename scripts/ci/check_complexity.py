#!/usr/bin/env python3
"""Failing xenon complexity gate for src/avo (task-010 / FR-5).

Enforces xenon ``--max-absolute B``. Blocks currently above B must appear in
``scripts/ci/complexity-allowlist.json`` with a reason and a complexity ceiling.
New or worsened debt fails CI; soft/warn-only mode is intentionally absent.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from radon.complexity import cc_rank
from xenon.core import analyze

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = Path(__file__).resolve().parent / "complexity-allowlist.json"
TARGET = ROOT / "src" / "avo"
MAX_ABSOLUTE = "B"
REPORT_PATH = ROOT / "reports" / "quality" / "complexity.json"


def _write_report(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _report() -> dict:
    return {
        "schema_version": 1,
        "gate": "complexity",
        "sha": os.environ.get("AVO_QUALITY_SHA") or os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("AVO_QUALITY_RUN_ID")
        or os.environ.get("GITHUB_RUN_ID"),
        "recorded_at": datetime.now(UTC).isoformat(),
        "status": "ERROR",
        "complete": False,
        "policy": {
            "scope": "src/avo",
            "max_absolute": MAX_ABSOLUTE,
            "allowlist_path": _norm_repo_path(ALLOWLIST_PATH),
        },
        "findings": [],
        "allowlisted": [],
        "violations": [],
        "worsened": [],
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


def _load_allowlist() -> dict[tuple[str, str], dict]:
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    if raw.get("max_absolute", MAX_ABSOLUTE).upper() != MAX_ABSOLUTE:
        raise SystemExit(
            f"allowlist max_absolute must be {MAX_ABSOLUTE!r}, "
            f"got {raw.get('max_absolute')!r}"
        )
    index: dict[tuple[str, str], dict] = {}
    for entry in raw.get("blocks", []):
        key = (str(entry["path"]).replace("\\", "/"), str(entry["name"]))
        if key in index:
            raise SystemExit(f"duplicate allowlist entry: {key[0]}::{key[1]}")
        if not entry.get("reason"):
            raise SystemExit(f"allowlist entry missing reason: {key[0]}::{key[1]}")
        index[key] = entry
    return index


def _check(report: dict) -> int:
    allowlist = _load_allowlist()
    report["policy"]["configured_allowlist_entries"] = len(allowlist)
    args = SimpleNamespace(
        path=[str(TARGET)],
        exclude=None,
        ignore=None,
        no_assert=False,
        absolute=MAX_ABSOLUTE,
        modules=None,
        average=None,
        averagenum=None,
        paths_in_front=False,
    )
    # Discard xenon's default logger noise; we report allowlist-aware results.
    logger = logging.getLogger("xenon.check_complexity")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    _infractions, results = analyze(args, logger)

    violations: list[str] = []
    worsened: list[str] = []
    seen: set[tuple[str, str]] = set()

    for module, blocks in sorted(results.items()):
        if isinstance(blocks, dict) and blocks.get("error"):
            violations.append(f"cannot parse {module}: {blocks['error']}")
            report["errors"].append(
                {"path": _norm_repo_path(module), "message": str(blocks["error"])}
            )
            continue
        rel = _norm_repo_path(module)
        for block in blocks:
            name = block["name"]
            complexity = int(block["complexity"])
            rank = cc_rank(complexity)
            key = (rel, name)
            finding = {
                "path": rel,
                "name": name,
                "line": int(block["lineno"]),
                "complexity": complexity,
                "rank": rank,
                "disposition": "within_policy",
            }
            report["findings"].append(finding)
            if rank <= MAX_ABSOLUTE:
                continue
            entry = allowlist.get(key)
            if entry is None:
                finding["disposition"] = "unwaived"
                report["violations"].append(finding)
                violations.append(
                    f"{rel}:{block['lineno']} {name} rank {rank} "
                    f"(cc={complexity}) exceeds max-absolute {MAX_ABSOLUTE}"
                )
                continue
            seen.add(key)
            ceiling = int(entry["complexity"])
            finding.update(
                disposition="allowlisted", reason=entry["reason"], ceiling=ceiling
            )
            report["allowlisted"].append(finding)
            if complexity > ceiling:
                finding["disposition"] = "worsened"
                report["worsened"].append(finding)
                worsened.append(
                    f"{rel}:{block['lineno']} {name} cc={complexity} "
                    f"exceeds allowlist ceiling {ceiling} "
                    f"(reason: {entry['reason']})"
                )

    stale = sorted(set(allowlist) - seen)
    report["stale"] = [allowlist[key] for key in stale]
    stale_msgs = [
        f"{path}::{name} allowlisted but no longer exceeds {MAX_ABSOLUTE} "
        f"— remove from complexity-allowlist.json"
        for path, name in stale
    ]

    print(f"==> quality:complexity (xenon max-absolute {MAX_ABSOLUTE})")
    print(f"    allowlist: {_norm_repo_path(ALLOWLIST_PATH)}")
    print(f"    allowlisted blocks: {len(allowlist)}")

    failed = False
    if violations:
        failed = True
        print("NEW complexity violations (not allowlisted):", file=sys.stderr)
        for line in violations:
            print(f"  ERROR: {line}", file=sys.stderr)
    if worsened:
        failed = True
        print("Allowlisted blocks grew worse:", file=sys.stderr)
        for line in worsened:
            print(f"  ERROR: {line}", file=sys.stderr)
    if stale_msgs:
        failed = True
        print("Stale allowlist entries:", file=sys.stderr)
        for line in stale_msgs:
            print(f"  ERROR: {line}", file=sys.stderr)

    report["complete"] = not report["errors"]
    report["status"] = "ERROR" if report["errors"] else "FAIL" if failed else "PASS"
    report["counts"] = {
        "measured_blocks": len(report["findings"]),
        "above_threshold": sum(
            item["rank"] > MAX_ABSOLUTE for item in report["findings"]
        ),
        "allowlisted": len(report["allowlisted"]),
        "unwaived": len(report["violations"]),
        "worsened": len(report["worsened"]),
        "stale": len(report["stale"]),
        "errors": len(report["errors"]),
    }
    if failed:
        return 1

    print("quality:complexity passed.")
    return 0


def main() -> int:
    report = _report()
    try:
        return _check(report)
    except (OSError, ValueError, TypeError, KeyError, SystemExit) as exc:
        report["errors"].append({"message": str(exc)})
        print(f"quality:complexity failed: {exc}", file=sys.stderr)
        return 1
    finally:
        _write_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
