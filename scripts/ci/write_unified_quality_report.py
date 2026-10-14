"""Join this run's quality and mutation evidence without re-running gates."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
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
    return all(isinstance(series.get(key), dict) for key in ("coverage", "duplication"))


def combine(
    quality_path: Path,
    mutation_path: Path | None,
    *,
    sha: str,
    run_id: str,
    needs: dict,
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
    if repository and run_id:
        doc["run_url"] = f"https://github.com/{repository}/actions/runs/{run_id}"
    dashboard = load_module("avo_ci_quality_dashboard", "quality_dashboard.py")
    doc["series"]["dashboard"] = dashboard.build_series(doc)
    doc["overall"] = doc["series"]["dashboard"]["overall"]
    return doc


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
    args = parser.parse_args()
    try:
        needs = json.loads(os.environ.get("CI_NEEDS_JSON", "{}"))
    except ValueError:
        needs = {}
    if not isinstance(needs, dict):
        needs = {}
    doc = combine(
        Path(args.quality),
        Path(args.mutation),
        sha=os.environ.get("GITHUB_SHA", ""),
        run_id=os.environ.get("GITHUB_RUN_ID", ""),
        needs=needs,
    )
    dashboard = load_module("avo_ci_quality_dashboard", "quality_dashboard.py")
    series = doc["series"]["dashboard"]
    image = ""
    try:
        dashboard.render(series, Path(args.charts_dir) / "dashboard.png")
        image = "kpi-chart:dashboard.png"
    except Exception as exc:
        print(f"Dashboard rendering unavailable: {exc}", file=sys.stderr)
    text = dashboard.markdown(doc, series, image=image)
    if not image:
        text += "\nDashboard image unavailable. Measurements remain in the table.\n"
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
