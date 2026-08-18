#!/usr/bin/env python3
"""Write a short Software quality sticky-comment markdown (Maxframe-style table)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

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

GATE_POLICY = {
    "lint": "Ruff (`src/avo`, `tests`, `helpers`) + ESLint",
    "format": "Ruff format --check + Prettier --check",
    "complexity": "xenon max-absolute **B** · Ruff C901 ≤ 31",
    "deps": "pip-audit + npm high+ (`deps-audit-allowlist.json`)",
    "deadcode": "vulture confidence ≥ 60 (`deadcode-allowlist.json`)",
    "duplication": "jscpd on `src/avo`",
    "architecture": "import-linter (`.importlinter`)",
    "tree": "npm find-dupes · command fail blocks · hoist plan report-only",
}


def _label(outcome: str) -> str:
    return OUTCOME_LABEL.get(
        outcome.strip().lower(), outcome.strip().upper() or "UNKNOWN"
    )


def _json_count(path: Path, key: str) -> int | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get(key)
    if isinstance(value, list):
        return len(value)
    return None


def coverage_detail(coverage_json: Path, floor: float) -> str:
    if not coverage_json.is_file():
        return f"fail-under **{floor:.0f}%** (summary json missing)"
    payload = json.loads(coverage_json.read_text(encoding="utf-8"))
    totals = payload.get("totals") or {}
    pct = totals.get("percent_covered")
    covered = totals.get("covered_lines")
    statements = totals.get("num_statements")
    if pct is None:
        return f"fail-under **{floor:.0f}%**"
    extra = ""
    if covered is not None and statements is not None:
        extra = f" · {covered}/{statements} lines"
    return f"**{float(pct):.2f}%** (floor {floor:.0f}%){extra}"


def gate_detail(key: str, *, coverage_json: Path, floor: float) -> str:
    if key == "coverage":
        return coverage_detail(coverage_json, floor)
    if key == "complexity":
        blocks = _json_count(ROOT / "scripts/ci/complexity-allowlist.json", "blocks")
        extra = f" · {blocks} allowlisted blocks" if blocks is not None else ""
        return GATE_POLICY[key] + extra
    if key == "deadcode":
        items = _json_count(ROOT / "scripts/ci/deadcode-allowlist.json", "items")
        extra = f" · {items} allowlisted names" if items is not None else ""
        return GATE_POLICY[key] + extra
    if key == "duplication":
        threshold = 2
        jscpd = ROOT / ".jscpd.json"
        if jscpd.is_file():
            threshold = int(
                json.loads(jscpd.read_text(encoding="utf-8")).get("threshold") or 2
            )
        return f"{GATE_POLICY[key]} · fail if clone rate > **{threshold}%**"
    if key == "deps":
        allow = ROOT / "scripts/ci/deps-audit-allowlist.json"
        npm_n = None
        if allow.is_file():
            npm = (json.loads(allow.read_text(encoding="utf-8")).get("npm") or {}).get(
                "advisory_ids"
            )
            if isinstance(npm, list):
                npm_n = len(npm)
        extra = f" · {npm_n} npm GHSA exceptions" if npm_n is not None else ""
        return GATE_POLICY[key] + extra
    return GATE_POLICY.get(key, "")


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
        "| Gate | Status | What this checks |",
        "|---|---|---|",
    ]
    for key, title in GATES:
        outcome = outcomes.get(key, "")
        detail = gate_detail(key, coverage_json=coverage_json, floor=floor)
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
