"""Unification must reject stale evidence and retain text after image failures."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def load():
    spec = importlib.util.spec_from_file_location(
        "unified_quality_report", ROOT / "scripts/ci/write_unified_quality_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence(tmp_path):
    from scripts.ci.write_quality_pr_report import GATES

    path = tmp_path / "quality.json"
    path.write_text(
        json.dumps(
            {
                "schema": 2,
                "sha": SHA,
                "run_id": "42",
                "overall": "PASS",
                "gates": [
                    {"key": key, "title": title, "status": "PASS", "metric": "measured"}
                    for key, title in GATES
                ],
                "series": {
                    "coverage": {"measured": 71, "floor": 68},
                    "duplication": {"measured": 1, "ceiling": 2},
                },
                "mutation_policy": {"profile": "light", "floor": 40},
            }
        )
    )
    return path


def test_matching_evidence_is_preserved(tmp_path):
    mod = load()
    doc = mod.combine(evidence(tmp_path), None, sha=SHA, run_id="42", needs={})
    assert doc["series"]["coverage"]["measured"] == 71
    assert doc["series"]["dashboard"]["metrics"][1]["measured"] == 1
    assert doc["overall"] == "INCOMPLETE"


def test_stale_run_cannot_supply_measurements(tmp_path):
    mod = load()
    doc = mod.combine(evidence(tmp_path), None, sha=SHA, run_id="43", needs={})
    assert doc["overall"] != "PASS"
    assert doc["series"]["dashboard"]["metrics"][0]["measured"] is None


def test_complete_mutation_and_jobs_produce_green(tmp_path):
    mod = load()
    mutation = tmp_path / "mutation.json"
    mutation.write_text(
        json.dumps(
            {
                "sha": SHA,
                "run_id": "42",
                "profile": "light",
                "floor": 40,
                "killed": 3,
                "survived": 1,
                "total": 4,
            }
        )
    )
    needs = {key: {"result": "success"} for key in mod.readiness().MANDATORY_JOBS}
    needs["ci-readiness"] = {"result": "success"}
    doc = mod.combine(evidence(tmp_path), mutation, sha=SHA, run_id="42", needs=needs)
    assert doc["overall"] == "PASS"
    needs["repo-integration-tests"]["result"] = "failure"
    doc = mod.combine(evidence(tmp_path), mutation, sha=SHA, run_id="42", needs=needs)
    assert doc["overall"] == "FAIL"


def test_duplicate_gate_evidence_is_rejected(tmp_path):
    mod = load()
    path = evidence(tmp_path)
    payload = json.loads(path.read_text())
    payload["gates"].append(payload["gates"][0])
    path.write_text(json.dumps(payload))
    doc = mod.combine(path, None, sha=SHA, run_id="42", needs={})
    assert doc["series"]["dashboard"]["metrics"][0]["measured"] is None


def test_unreadable_evidence_stays_actionable(tmp_path):
    mod = load()
    path = tmp_path / "broken.json"
    path.write_text("{")
    doc = mod.combine(path, None, sha=SHA, run_id="42", needs={})
    assert doc["overall"] != "PASS"
    assert doc["series"]["dashboard"]["actions"]
    assert doc["overall"] == "INCOMPLETE"


def test_hosting_does_not_duplicate_the_unified_summary(tmp_path, monkeypatch):
    import sys

    from scripts.ci import upload_kpi_chart_images as uploader

    markdown = tmp_path / "report.md"
    markdown.write_text("One text report.\n")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(
        sys,
        "argv",
        ["upload_kpi_chart_images.py", "--markdown", str(markdown), "--no-summary"],
    )
    assert uploader.main() == 0
    assert not summary.exists()
