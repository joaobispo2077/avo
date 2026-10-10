#!/usr/bin/env python3
"""Write a Software metrics sticky-comment (status + numbers + what the gate checks)."""

from __future__ import annotations

import argparse
import json
import os
import re
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
    "coverage": "pytest-cov fail-under on `src/avo`",
    "complexity": "xenon max-absolute **B** · Ruff C901 ≤ 31",
    "deps": "pip-audit + npm critical (`deps-audit-allowlist.json`); high/moderate/low reported",
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


def coverage_floor_from_pyproject(path: Path) -> float:
    """Real pytest-cov fail_under. Does not invent a second target."""
    text = path.read_text(encoding="utf-8")
    marker = "[tool.coverage.report]"
    if marker not in text:
        raise SystemExit(f"{path} is missing {marker}")
    body = text.split(marker, 1)[1].split("\n[", 1)[0]
    match = re.search(r"(?m)^fail_under\s*=\s*(\d+(?:\.\d+)?)\s*$", body)
    if not match:
        raise SystemExit(f"{path} is missing coverage fail_under")
    return float(match.group(1))


def overall_label(outcomes: dict[str, str]) -> str:
    """PASS only when every Software quality gate step succeeded."""
    passed = all(
        outcomes.get(key, "").strip().lower() == "success" for key, _title in GATES
    )
    return "PASS" if passed else "FAIL"


def outcomes_from_env() -> dict[str, str]:
    return {key: os.environ.get(f"Q_{key.upper()}", "") for key, _title in GATES}


def gate_outcomes_path(report_path: Path) -> Path:
    return report_path.parent / "gate-outcomes.json"


def write_gate_outcomes(path: Path, outcomes: dict[str, str]) -> None:
    """Sidecar the report table uses, so later steps cannot invent other statuses."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"gates": {key: outcomes.get(key, "") for key, _title in GATES}}
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def load_gate_outcomes(path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    gates = payload.get("gates") if isinstance(payload, dict) else None
    if not isinstance(gates, dict):
        return None
    return {key: str(gates.get(key, "") or "") for key, _title in GATES}


def coverage_numbers(coverage_json: Path) -> dict[str, float | int | None]:
    if not coverage_json.is_file():
        return {"percent": None, "covered": None, "statements": None}
    payload = json.loads(coverage_json.read_text(encoding="utf-8"))
    totals = payload.get("totals") or {}
    percent = totals.get("percent_covered")
    return {
        "percent": None if percent is None else float(percent),
        "covered": totals.get("covered_lines"),
        "statements": totals.get("num_statements"),
    }


def complexity_allowlisted(root: Path = ROOT) -> int | None:
    return _json_count(root / "scripts/ci/complexity-allowlist.json", "blocks")


def deadcode_allowlisted(root: Path = ROOT) -> int | None:
    return _json_count(root / "scripts/ci/deadcode-allowlist.json", "items")


def npm_audit_reported(root: Path = ROOT) -> str | None:
    """Sticky metric from the npm audit summary written by check_npm_audit.py."""
    path = root / "reports" / "quality" / "npm-audit-summary.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    label = "PASS" if payload.get("ok") else "FAIL"
    if (
        payload.get("error")
        or payload.get("critical") is None
        or payload.get("high") is None
    ):
        return (
            f"FAIL, counts unknown: {payload.get('error') or 'npm audit not completed'}"
        )
    critical = int(payload.get("critical") or 0)
    high = int(payload.get("high") or 0)
    result = f"{label}, {critical} critical, {high} high reported"
    if "moderate" in payload and "low" in payload:
        result += f", {payload['moderate']} moderate, {payload['low']} low reported"
    return result


def npm_exception_count(root: Path = ROOT) -> int:
    allow = root / "scripts/ci/deps-audit-allowlist.json"
    if not allow.is_file():
        return 0
    npm = (json.loads(allow.read_text(encoding="utf-8")).get("npm") or {}).get(
        "advisory_ids"
    )
    if isinstance(npm, list):
        return len(npm)
    return 0


def deps_findings_path(root: Path = ROOT) -> Path:
    return root / "reports" / "quality" / "deps-findings.json"


def load_deps_findings(path: Path) -> list[dict]:
    """Audit findings recorded by the deps gate. Missing file means none."""
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    raw = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("package")]


def format_deps_finding(finding: dict) -> str:
    """One finding. No waiver count. Package and via path; id when one exists."""
    package = str(finding.get("package") or "").strip()
    advisory = finding.get("id")
    advisory_id = advisory.strip() if isinstance(advisory, str) else ""
    via = finding.get("via")
    via_path = via.strip() if isinstance(via, str) else ""
    if advisory_id and via_path:
        return f"{package} {advisory_id} via {via_path}"
    if advisory_id:
        return f"{package} {advisory_id}"
    if via_path:
        return f"{package} via {via_path} has no GHSA id"
    return f"{package} has no GHSA id"


def deps_cell(
    outcome: str,
    *,
    root: Path = ROOT,
    findings_path: Path | None = None,
) -> str:
    """Sticky Dependency audit metric.

    FAIL lists every recorded unwaived finding. PASS keeps the waiver count.
    Charts keep using ``gate_metric``.
    """
    path = findings_path if findings_path is not None else deps_findings_path(root)
    if outcome.strip().lower() not in {"success", "failure"}:
        return "not measured"
    if outcome.strip().lower() == "failure":
        diagnostic = None
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return "dependency audit evidence unreadable"
            if isinstance(payload, dict) and payload.get("error"):
                diagnostic = str(payload["error"])
        findings = load_deps_findings(path)
        if findings:
            details = "; ".join(format_deps_finding(item) for item in findings)
            return f"{diagnostic}; {details}" if diagnostic else details
        if diagnostic:
            return diagnostic
        return "dependency audit failed; no finding evidence available"
    reported = npm_audit_reported(root)
    if reported:
        return reported
    return f"{npm_exception_count(root)} npm GHSA exceptions"


def duplication_ceiling(root: Path = ROOT) -> int:
    threshold = 2
    jscpd = root / ".jscpd.json"
    if jscpd.is_file():
        raw = json.loads(jscpd.read_text(encoding="utf-8")).get("threshold") or 2
        threshold = int(raw)
    return threshold


def duplication_measured(root: Path = ROOT) -> float | None:
    """Line percentage from the jscpd JSON report. Missing file has no measurement."""
    path = root / "reports" / "quality" / "jscpd" / "jscpd-report.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    statistics = payload.get("statistics")
    total = statistics.get("total") if isinstance(statistics, dict) else None
    raw = total.get("percentage") if isinstance(total, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def architecture_contracts(root: Path = ROOT) -> int | None:
    config = root / ".importlinter"
    if not config.is_file():
        return None
    return config.read_text(encoding="utf-8").count("[importlinter:contract:")


def coverage_detail(coverage_json: Path, floor: float) -> str:
    if not coverage_json.is_file():
        return f"— (floor {floor:.0f}%, json missing)"
    numbers = coverage_numbers(coverage_json)
    percent = numbers["percent"]
    if percent is None:
        return f"floor {floor:.0f}%"
    extra = ""
    covered = numbers["covered"]
    statements = numbers["statements"]
    if covered is not None and statements is not None:
        extra = f" · {covered}/{statements} lines"
    return f"{float(percent):.2f}% (floor {floor:.0f}%){extra}"


def gate_metric(
    key: str,
    *,
    coverage_json: Path,
    floor: float,
    root: Path = ROOT,
    outcome: str | None = None,
) -> str:
    if key == "deps" and outcome is not None:
        return deps_cell(outcome, root=root)
    if key == "coverage":
        return coverage_detail(coverage_json, floor)
    if key == "complexity":
        blocks = complexity_allowlisted(root)
        return f"{blocks} allowlisted" if blocks is not None else "allowlist n/a"
    if key == "deadcode":
        items = deadcode_allowlisted(root)
        return f"{items} allowlisted" if items is not None else "allowlist n/a"
    if key == "deps":
        reported = npm_audit_reported(root)
        if reported:
            return reported
        return f"{npm_exception_count(root)} npm GHSA exceptions"
    if key == "duplication":
        ceiling = duplication_ceiling(root)
        measured = duplication_measured(root)
        if measured is None:
            return f"ceiling {ceiling}%"
        return f"{measured:.2f}% (ceiling {ceiling}%)"
    if key == "architecture":
        contracts = architecture_contracts(root)
        return "—" if contracts is None else f"{contracts} contracts"
    return "—"


def build_markdown(
    outcomes: dict[str, str],
    *,
    coverage_json: Path,
    floor: float,
    root: Path = ROOT,
    findings_path: Path | None = None,
) -> str:
    lines = [
        "## Software metrics",
        "",
        f"**Overall: {overall_label(outcomes)}**",
        "",
        "Fast gates from the **Software quality** job. Later rows are SKIPPED when an earlier gate fails immediately.",
        "",
        "| Gate | Status | Metric | What this checks |",
        "|---|---|---|---|",
    ]
    for key, title in GATES:
        outcome = outcomes.get(key, "")
        if key == "deps":
            metric = deps_cell(outcome, root=root, findings_path=findings_path)
        else:
            metric = gate_metric(
                key, coverage_json=coverage_json, floor=floor, root=root
            )
        policy = GATE_POLICY.get(key, "")
        lines.append(f"| {title} | **{_label(outcome)}** | {metric} | {policy} |")
    lines.extend(
        [
            "",
            f"Coverage fail-under **{floor:.0f}%**. Mutation is a separate comment.",
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
    parser.add_argument(
        "--floor",
        type=float,
        default=None,
        help="Coverage fail_under. Default: [tool.coverage.report] fail_under.",
    )
    args = parser.parse_args()
    floor = (
        args.floor
        if args.floor is not None
        else coverage_floor_from_pyproject(ROOT / "pyproject.toml")
    )
    outcomes = outcomes_from_env()
    text = build_markdown(
        outcomes,
        coverage_json=Path(args.coverage),
        floor=floor,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    write_gate_outcomes(gate_outcomes_path(out), outcomes)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(text)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
