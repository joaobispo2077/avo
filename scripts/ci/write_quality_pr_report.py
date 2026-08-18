#!/usr/bin/env python3
"""Write a short Software quality sticky-comment markdown (Maxframe-style table)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

GATES = (
    ("lint", "Lint"),
    ("format", "Format"),
    ("coverage", "Coverage"),
    ("complexity", "Complexity"),
    ("deps", "Dependency audit"),
    ("deadcode", "Dead code"),
    ("duplication", "Duplication"),
    ("architecture", "Architecture"),
    ("tree", "Dependency tree"),
)

OUTCOME_LABEL = {
    "success": "PASS",
    "failure": "FAIL",
    "skipped": "SKIPPED",
    "cancelled": "CANCELLED",
    "": "UNKNOWN",
}


def _label(outcome: str) -> str:
    return OUTCOME_LABEL.get(
        outcome.strip().lower(), outcome.strip().upper() or "UNKNOWN"
    )


def coverage_detail(coverage_json: Path, floor: float) -> str:
    if not coverage_json.is_file():
        return f"floor {floor:.0f}% (summary json missing)"
    payload = json.loads(coverage_json.read_text(encoding="utf-8"))
    totals = payload.get("totals") or {}
    pct = totals.get("percent_covered")
    covered = totals.get("covered_lines")
    statements = totals.get("num_statements")
    if pct is None:
        return f"floor {floor:.0f}%"
    extra = ""
    if covered is not None and statements is not None:
        extra = f" · {covered}/{statements} lines"
    return f"{float(pct):.2f}% (floor {floor:.0f}%){extra}"


def build_markdown(
    outcomes: dict[str, str],
    *,
    coverage_json: Path,
    floor: float,
) -> str:
    lines = [
        "## Software quality",
        "",
        "Fast gates from the **Software quality** job. Later rows are SKIPPED when an earlier gate fails immediately.",
        "",
        "| Gate | Status | Detail |",
        "|---|---|---|",
    ]
    for key, title in GATES:
        outcome = outcomes.get(key, "")
        detail = ""
        if key == "coverage":
            detail = coverage_detail(coverage_json, floor)
        lines.append(f"| {title} | **{_label(outcome)}** | {detail} |")
    lines.extend(
        [
            "",
            f"- Coverage floor: **{floor:.0f}%** (unchanged)",
            "- Mutation is a separate sticky comment (`Mutation tests`)",
            "",
            "_Generated from CI Software quality step outcomes_",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--coverage", default="reports/quality/coverage.json")
    parser.add_argument("--floor", type=float, default=68.0)
    args = parser.parse_args()
    outcomes = {key: os.environ.get(f"Q_{key.upper()}", "") for key, _title in GATES}
    text = build_markdown(
        outcomes,
        coverage_json=Path(args.coverage),
        floor=args.floor,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(text)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
