#!/usr/bin/env python3
"""Report measured safety branches. Informational; no additional quality floor."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCOPES = (
    (
        "Canonical sources and ancestry",
        (
            "src/avo/timeline/lineage.py",
            "src/avo/timeline/picture_lineage.py",
            "src/avo/timeline/proof_plan.py",
        ),
    ),
    (
        "Approval integrity",
        ("src/avo/timeline/approval_service.py", "src/avo/timeline/review.py"),
    ),
    ("Timeline mappings", ("src/avo/timeline/mapping.py",)),
    ("Cleanup preservation", ("src/avo/project_inventory.py",)),
    (
        "Destructive request state",
        ("src/avo/mcp/request_state.py", "src/avo/mcp/mrtr.py"),
    ),
)


def _scope_path(name: str, root: Path) -> str:
    normalized = name.replace("\\", "/").removeprefix("./")
    prefix = root.resolve().as_posix().rstrip("/") + "/"
    if normalized.lower().startswith(prefix.lower()):
        return normalized[len(prefix) :]
    return normalized


def _file_counts(path: str, payload: dict) -> dict:
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        raise ValueError(f"{path}: branch summary missing")
    counts = [
        summary.get(key)
        for key in ("covered_branches", "num_branches", "missing_branches")
    ]
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError(f"{path}: invalid branch counts")
    covered, total, missing = counts
    arcs = payload.get("missing_branches")
    if not isinstance(arcs, list) or any(
        not isinstance(arc, list)
        or len(arc) != 2
        or any(type(line) is not int for line in arc)
        or arc[0] < 1
        for arc in arcs
    ):
        raise ValueError(f"{path}: invalid missing branch locations")
    if covered + missing != total or len({tuple(arc) for arc in arcs}) != missing:
        raise ValueError(f"{path}: inconsistent branch counts or locations")
    return {
        "path": path,
        "measured": True,
        "covered_branches": covered,
        "num_branches": total,
        "missing_branches": sorted(arcs),
    }


def _totals(rows: list[dict]) -> dict:
    covered = sum(row.get("covered_branches", 0) for row in rows)
    total = sum(row.get("num_branches", 0) for row in rows)
    return {
        "covered_branches": covered,
        "num_branches": total,
        "missing_branches": total - covered,
        "percent": 100.0 * covered / total if total else None,
        "complete": all(row["measured"] for row in rows),
    }


def build_report(
    profile: dict,
    *,
    sha: str,
    run_id: str,
    recorded_at: str,
    test_outcome: str,
    suite: str,
    root: Path = ROOT,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("a full commit SHA is required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", run_id):
        raise ValueError("a run_id is required")
    datetime.strptime(recorded_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if test_outcome not in {"success", "failure", "skipped", "cancelled", "unknown"}:
        raise ValueError("invalid test outcome")
    meta = profile.get("meta") if isinstance(profile, dict) else None
    if not isinstance(meta, dict) or meta.get("branch_coverage") is not True:
        raise ValueError("coverage JSON requires branch instrumentation")
    if not isinstance(profile.get("files"), dict):
        raise ValueError("coverage JSON files missing")
    measured = {}
    for name, payload in profile["files"].items():
        path = _scope_path(name, root)
        if path in measured:
            raise ValueError(f"duplicate coverage source: {path}")
        measured[path] = payload
    groups = []
    all_rows = []
    for label, paths in SCOPES:
        rows = [
            _file_counts(path, measured[path])
            if path in measured
            else {"path": path, "measured": False}
            for path in paths
        ]
        groups.append({"name": label, **_totals(rows), "files": rows})
        all_rows.extend(rows)
    return {
        "schema": 1,
        "sha": sha,
        "run_id": run_id,
        "recorded_at": recorded_at,
        "coverage_timestamp": profile["meta"].get("timestamp"),
        "test_outcome": test_outcome,
        "suite": suite,
        "groups": groups,
        "totals": _totals(all_rows),
    }


def _percent(row: dict) -> str:
    if row["percent"] is None:
        return "no measured branches" if row["complete"] else "not measured"
    suffix = "" if row["complete"] else " (partial scope)"
    return f"{row['percent']:.2f}%{suffix}"


def render_markdown(report: dict) -> str:
    lines = [
        "# Safety branch coverage",
        "",
        (
            "Informational measurement of existing safety files; no new coverage floor. "
            "Percentages use covered branch outcomes divided by total measured branch outcomes, "
            "rather than averages of file percentages. Missing files are not counted as covered."
        ),
        "",
        f"Checkout SHA: `{report['sha']}` · Run: `{report['run_id']}` · Recorded (UTC): {report['recorded_at']}",
        "",
        f"Suite: {report['suite']} · Test outcome: **{report['test_outcome']}**",
        "",
        "A failing or interrupted suite is incomplete evidence, even when some branches were measured.",
        "",
        "| Risk scope | Covered / total branches | Branch coverage |",
        "|---|---:|---|",
    ]
    for group in [
        *report["groups"],
        {"name": "All measured safety files", **report["totals"]},
    ]:
        counts = f"{group['covered_branches']} / {group['num_branches']}"
        lines.append(f"| {group['name']} | {counts} | {_percent(group)} |")
    for group in report["groups"]:
        lines.extend(
            ["", f"<details><summary>{group['name']}: source locations</summary>", ""]
        )
        for row in group["files"]:
            path = row["path"]
            if not row["measured"]:
                lines.append(f"- `{path}`: not measured")
                continue
            lines.append(
                f"- `{path}`: {row['covered_branches']} / {row['num_branches']} branches"
            )
            for source, destination in row["missing_branches"]:
                target = f"line {destination}" if destination > 0 else "exit"
                lines.append(f"  - Uncovered `{path}:{source}` to {target}")
        lines.extend(["", "</details>"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", default="reports/quality/branch-coverage.json")
    parser.add_argument("--out", default="reports/quality/branch-risk.json")
    parser.add_argument("--markdown", default="reports/quality/branch-risk.md")
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--test-outcome", default="unknown")
    parser.add_argument(
        "--suite", default="core unit suite (project and integration tests excluded)"
    )
    parser.add_argument("--recorded-at", default="")
    args = parser.parse_args(argv)
    try:
        profile = json.loads(Path(args.coverage).read_text(encoding="utf-8"))
        report = build_report(
            profile,
            sha=args.sha.strip().lower(),
            run_id=args.run_id,
            recorded_at=args.recorded_at
            or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            test_outcome=args.test_outcome,
            suite=args.suite,
        )
        markdown = render_markdown(report)
        for path, content in (
            (Path(args.out), json.dumps(report, indent=2, sort_keys=True) + "\n"),
            (Path(args.markdown), markdown),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"branch risk report failed: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.out} and {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
