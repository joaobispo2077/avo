"""Join this run's quality and mutation evidence without re-running gates."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, filename: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).with_name(filename)
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {filename}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def readiness():
    return load_module("avo_ci_readiness", "check_ci_readiness.py")


def read_json(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def quality_evidence(payload: dict | None, sha: str, run_id: str) -> bool:
    if not payload or payload.get("schema") != 2:
        return False
    if payload.get("sha") != sha or str(payload.get("run_id") or "") != run_id:
        return False
    if "reporting" in payload:
        measurements = load_module(
            "avo_ci_quality_measurements", "quality_measurements.py"
        )
        if (
            measurements.validate_reporting_context(payload)
            or payload["reporting"].get("mode") != "ci"
        ):
            return False
    if "coverage_precision" in payload and (
        type(payload["coverage_precision"]) is not int
        or not 0 <= payload["coverage_precision"] <= 9
    ):
        return False
    gates, series = payload.get("gates"), payload.get("series")
    if not isinstance(gates, list) or not isinstance(series, dict):
        return False
    if not all(
        isinstance(row, dict)
        and all(isinstance(row.get(key), str) for key in ("key", "title", "status"))
        for row in gates
    ):
        return False
    report = load_module("avo_ci_write_quality_pr_report", "write_quality_pr_report.py")
    if [(row["key"], row["title"]) for row in gates] != list(report.GATES):
        return False
    if "measurement_evidence" in payload and (
        not isinstance(payload["measurement_evidence"], dict)
        or payload["measurement_evidence"].get("schema") != 1
    ):
        return False
    return all(isinstance(series.get(key), dict) for key in ("coverage", "duplication"))


def combine(
    quality_path: Path,
    mutation_path: Path | None,
    *,
    sha: str,
    run_id: str,
    needs: dict,
    unit_path: Path | None = None,
    integration_path: Path | None = None,
) -> dict:
    doc = read_json(quality_path)
    if not quality_evidence(doc, sha, run_id):
        report = load_module(
            "avo_ci_write_quality_pr_report", "write_quality_pr_report.py"
        )
        doc = {
            "schema": 2,
            "sha": sha,
            "run_id": run_id,
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "gates": [
                {
                    "key": key,
                    "title": title,
                    "status": "UNKNOWN",
                    "metric": "Current-run quality evidence unavailable.",
                }
                for key, title in report.GATES
            ],
            "series": {},
            "measurement_evidence": {"schema": 1},
        }
    statuses = [row["status"] for row in doc["gates"]]
    doc["overall"] = (
        "FAIL"
        if any(status in {"FAIL", "CANCELLED"} for status in statuses)
        else "PASS"
        if all(status == "PASS" for status in statuses)
        else "INCOMPLETE"
    )
    doc["mutation"] = read_json(mutation_path)
    doc["jobs"] = {
        name: str(needs.get(name, {}).get("result") or "unknown")
        if isinstance(needs.get(name), dict)
        else "unknown"
        for name in readiness().MANDATORY_JOBS
    }
    ready = needs.get("ci-readiness")
    doc["jobs"]["ci-readiness"] = (
        str(ready.get("result") or "unknown") if isinstance(ready, dict) else "unknown"
    )
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) and re.fullmatch(
        r"[0-9]{1,20}", run_id
    ):
        doc["run_url"] = f"https://github.com/{repository}/actions/runs/{run_id}"
        doc["repository"] = repository
    measurements = load_module("avo_ci_quality_measurements", "quality_measurements.py")
    doc["reporting"] = measurements.reporting_context(
        sha=sha, run_id=run_id, repository=doc.get("repository", "")
    )
    if "measurement_evidence" in doc:
        doc["measurement_evidence"] = measurements.collect(doc, quality_path.parent)
        measurements.add_mutation(doc["measurement_evidence"], doc, mutation_path)
        measurements.add_mutation_scopes(
            doc["measurement_evidence"],
            doc,
            mutation_path.with_name("mutation-scopes.json") if mutation_path else None,
        )
    doc["artifact_urls"] = {}
    for job, artifact in (
        ("software-quality", "quality-evidence"),
        ("mutation-light", "mutation-reports-light"),
        ("repo-unit-tests", "unit-test-evidence"),
        ("repo-integration-tests", "integration-test-evidence"),
    ):
        outcome = needs.get(job, {})
        outputs = outcome.get("outputs", {}) if isinstance(outcome, dict) else {}
        url = outputs.get("evidence_url", "") if isinstance(outputs, dict) else ""
        prefix = doc.get("run_url", "") + "/artifacts/"
        if (
            isinstance(url, str)
            and doc.get("run_url")
            and url.startswith(prefix)
            and url.removeprefix(prefix).isdigit()
        ):
            doc["artifact_urls"][artifact] = url
    if unit_path is not None or integration_path is not None:
        executions = load_module(
            "avo_ci_test_execution_evidence", "test_execution_evidence.py"
        )
        doc["test_evidence"] = {
            job: executions.read_test_evidence(
                path,
                sha=sha,
                run_id=run_id,
                gate=gate,
                artifact=artifact,
                junit_name=filename,
            )
            for job, path, gate, artifact, filename in (
                (
                    "repo-unit-tests",
                    unit_path,
                    "unit-tests",
                    "unit-test-evidence",
                    "unit-tests.xml",
                ),
                (
                    "repo-integration-tests",
                    integration_path,
                    "integration-tests",
                    "integration-test-evidence",
                    "integration-tests.xml",
                ),
            )
            if path is not None
        }
    dashboard = load_module("avo_ci_quality_dashboard", "quality_dashboard.py")
    measurements.freeze_definitions(doc)
    dashboard.build_supporting(doc)
    doc["series"]["dashboard"] = dashboard.build_series(doc)
    doc["overall"] = doc["series"]["dashboard"]["overall"]
    return doc


def text_only_fallback(needs: dict) -> str:
    """Report the builder failure without importing the full reporting stack."""
    sha = os.environ.get("GITHUB_SHA", "")
    sha = sha if re.fullmatch(r"[0-9a-f]{40}", sha) else ""
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_id = run_id if re.fullmatch(r"[0-9]{1,20}", run_id) else ""
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    repository = (
        repository
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        else ""
    )
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    attempt = str(int(attempt)) if re.fullmatch(r"[1-9][0-9]{0,8}", attempt) else ""
    ci = os.environ.get("GITHUB_ACTIONS") == "true" and sha and run_id and repository
    event = (
        read_json(Path(os.environ.get("GITHUB_EVENT_PATH", "")))
        if os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        else None
    )
    pr = event.get("pull_request") if isinstance(event, dict) else None
    number = event.get("number") if isinstance(event, dict) else None
    pr_number = number if type(number) is int and number > 0 else None
    revisions = {}
    for side in ("head", "base"):
        record = pr.get(side) if isinstance(pr, dict) else None
        value = record.get("sha") if isinstance(record, dict) else None
        revisions[side] = (
            value
            if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value)
            else ""
        )
    lines = [
        "## AVO quality",
        "",
        "**Overall: FAIL**",
        "",
        (
            "The quality report builder failed. Measurements are unavailable; "
            "this text fallback does not certify release evidence."
        ),
        "",
    ]
    if not ci:
        lines.extend(["**Local preview**: this is not CI or release evidence.", ""])
    if pr_number is not None:
        lines.extend([f"PR: #{pr_number}", ""])
    for label, value in (
        ("PR head", revisions["head"]),
        ("PR base", revisions["base"]),
        ("Tested revision", sha),
    ):
        lines.append(f"{label}: `{value}`" if value else f"{label}: Unavailable")
        lines.append("")
    url = f"https://github.com/{repository}/actions/runs/{run_id}" if ci else ""
    if url and attempt:
        url += f"/attempts/{attempt}"
    run = f"[{run_id}]({url})" if url else run_id or "Unavailable"
    lines.extend(
        [
            f"Run: {run} · Attempt: {attempt or 'Unavailable'}",
            "",
            (
                "**Action:** Inspect the report builder failure in this run. "
                "Current producer evidence and mandatory-job outcomes remain "
                "separate from this reporting failure."
            ),
            "",
            "| Required job | Outcome |",
            "| --- | --- |",
        ]
    )
    outcomes = {"success", "failure", "skipped", "cancelled", "timed_out"}
    for job in (*readiness().MANDATORY_JOBS, "ci-readiness"):
        value = needs.get(job)
        result = value.get("result") if isinstance(value, dict) else None
        label = (
            result.upper()
            if isinstance(result, str) and result in outcomes
            else "UNKNOWN"
        )
        lines.append(f"| {job} | {label} |")
    lines.extend(
        [
            "",
            (
                "Coverage, duplication, mutation, complexity, CRAP and file coupling: "
                "Unavailable in this fallback. No previous run's values were reused."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quality", default="reports/quality/evidence/quality-metrics.json"
    )
    parser.add_argument(
        "--mutation", default="reports/mutation/evidence/mutation-metrics.json"
    )
    parser.add_argument("--out", default="reports/quality/quality-gates.md")
    parser.add_argument("--metrics", default="reports/quality/quality-metrics.json")
    parser.add_argument("--charts-dir", default="reports/quality/charts")
    parser.add_argument("--text-only-fallback", action="store_true")
    parser.add_argument("--unit-evidence", default="reports/quality/unit-evidence")
    parser.add_argument(
        "--integration-evidence", default="reports/quality/integration-evidence"
    )
    args = parser.parse_args()
    try:
        needs = json.loads(os.environ.get("CI_NEEDS_JSON", "{}"))
    except ValueError:
        needs = {}
    if not isinstance(needs, dict):
        needs = {}
    if args.text_only_fallback:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text_only_fallback(needs), encoding="utf-8", newline="\n")
        print("Wrote text-only report after quality builder failure.")
        return 0
    doc = combine(
        Path(args.quality),
        Path(args.mutation),
        sha=os.environ.get("GITHUB_SHA", ""),
        run_id=os.environ.get("GITHUB_RUN_ID", ""),
        needs=needs,
        unit_path=Path(args.unit_evidence),
        integration_path=Path(args.integration_evidence),
    )
    dashboard = load_module("avo_ci_quality_dashboard", "quality_dashboard.py")
    series = doc["series"]["dashboard"]
    dashboard.render_supporting(doc, Path(args.charts_dir).parent)
    image = ""
    try:
        dashboard.render(series, Path(args.charts_dir) / "dashboard.png")
        image = "kpi-chart:dashboard.png"
    except Exception as exc:
        print(f"Dashboard rendering unavailable: {exc}", file=sys.stderr)
        doc["image_error"] = f"{type(exc).__name__}: dashboard image unavailable"
        (Path(args.charts_dir) / "dashboard.png").unlink(missing_ok=True)
    text = dashboard.markdown(doc, series, image=image)
    for path, contents in (
        (Path(args.out), text),
        (Path(args.metrics), json.dumps(doc, indent=2, sort_keys=True) + "\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8", newline="\n")
    print(f"Wrote unified quality evidence and report: {series['overall']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
