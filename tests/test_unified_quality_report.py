"""Unification must reject stale evidence and retain text after image failures."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

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


def test_artifact_linking_does_not_duplicate_the_unified_summary(tmp_path, monkeypatch):
    import sys

    from scripts.ci import link_quality_artifacts as linker

    markdown = tmp_path / "report.md"
    markdown.write_text("One text report.\n")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(
        sys,
        "argv",
        ["link_quality_artifacts.py", "--markdown", str(markdown), "--no-summary"],
    )
    assert linker.main() == 0
    assert not summary.exists()


def captured_output(directory, gate, filename, payload):
    gate_dir = directory / "gates" / gate
    gate_dir.mkdir(parents=True)
    log = gate_dir / "gate.log"
    log.write_bytes(b"Captured analyzer output.\n")
    raw = directory / filename
    raw.write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
    )

    def record(path):
        content = path.read_bytes()
        return {
            "path": "reports/quality/" + path.relative_to(directory).as_posix(),
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "reason": None,
        }

    receipt = {
        "schema_version": 1,
        "sha": SHA,
        "run_id": "42",
        "gate": gate,
        "status": "PASS",
        "exit_code": 0,
        "log": record(log),
        "artifacts": [record(raw)],
    }
    (gate_dir / "gate.json").write_text(json.dumps(receipt), encoding="utf-8")
    return raw


def test_publisher_recollects_downloaded_inputs_instead_of_cached_measurements(
    tmp_path,
):
    mod = load()
    path = evidence(tmp_path)
    payload = json.loads(path.read_text())
    payload["measurement_evidence"] = {
        "schema": 1,
        "metrics": [{"key": "coverage", "state": "MEASURED", "number": 99}],
    }
    path.write_text(json.dumps(payload))
    raw = captured_output(
        tmp_path,
        "coverage",
        "coverage.json",
        {"totals": {"covered_lines": 7, "num_statements": 10, "percent_covered": 99}},
    )
    doc = mod.combine(path, None, sha=SHA, run_id="42", needs={})
    row = next(
        row
        for row in doc["measurement_evidence"]["metrics"]
        if row["key"] == "coverage"
    )
    assert row["number"] == 70
    assert row["sources"][0]["sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert doc["series"]["dashboard"]["metrics"][0]["measured"] == 70

    raw.write_text(json.dumps({"totals": {"covered_lines": 8, "num_statements": 10}}))
    rejected = mod.combine(path, None, sha=SHA, run_id="42", needs={})
    row = next(
        row
        for row in rejected["measurement_evidence"]["metrics"]
        if row["key"] == "coverage"
    )
    assert row["state"] == "UNAVAILABLE" and row["number"] is None
    assert rejected["series"]["dashboard"]["metrics"][0]["measured"] is None


def test_missing_quality_artifact_keeps_all_metrics_unavailable(tmp_path):
    mod = load()
    needs = {
        name: {"result": "success"}
        for name in (*mod.readiness().MANDATORY_JOBS, "ci-readiness")
    }
    doc = mod.combine(
        tmp_path / "missing.json", None, sha=SHA, run_id="42", needs=needs
    )
    measurements = doc["measurement_evidence"]["metrics"]
    assert len(measurements) == 11
    assert all(
        row["state"] == "UNAVAILABLE" and row["number"] is None for row in measurements
    )
    assert all(
        row["value"] == "Unavailable" and not row["sources"] for row in measurements
    )
    assert doc["overall"] == "INCOMPLETE"


@pytest.mark.parametrize(
    ("url", "accepted"),
    [
        ("https://github.com/owner/avo/actions/runs/42/artifacts/7", True),
        ("https://github.com/owner/avo/actions/runs/41/artifacts/7", False),
        ("https://github.com/other/avo/actions/runs/42/artifacts/7", False),
        ("https://github.com/owner/avo/actions/runs/42/artifacts/7?run=42", False),
        ("https://github.com/owner/avo/actions/runs/42/artifacts/latest", False),
        ("https://example.com/artifacts/7", False),
    ],
)
def test_artifact_links_are_bound_to_this_repository_and_run(
    tmp_path, monkeypatch, url, accepted
):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/avo")
    doc = load().combine(
        evidence(tmp_path),
        None,
        sha=SHA,
        run_id="42",
        needs={
            "software-quality": {"result": "success", "outputs": {"evidence_url": url}}
        },
    )
    assert doc["run_url"] == "https://github.com/owner/avo/actions/runs/42"
    assert doc["artifact_urls"] == ({"quality-evidence": url} if accepted else {})


def test_publisher_cli_reads_junit_and_leaves_missing_counts_unavailable(
    tmp_path, monkeypatch
):
    import sys

    mod = load()
    quality = evidence(tmp_path)
    payload = json.loads(quality.read_text())
    payload["test_evidence"] = {"repo-integration-tests": {"counts": {"total": 999}}}
    quality.write_text(json.dumps(payload))
    unit = tmp_path / "downloaded-unit"
    captured_output(
        unit,
        "unit-tests",
        "unit-tests.xml",
        '<testsuites tests="999"><testsuite><testcase name="pass"/>'
        '<testcase name="skip"><skipped/></testcase></testsuite></testsuites>',
    )
    integration = tmp_path / "missing-integration"
    output, metrics = tmp_path / "report.md", tmp_path / "metrics.json"
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv(
        "CI_NEEDS_JSON",
        json.dumps(
            {
                "repo-unit-tests": {"result": "success"},
                "repo-integration-tests": {"result": "success"},
            }
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "write_unified_quality_report.py",
            "--quality",
            str(quality),
            "--mutation",
            str(tmp_path / "missing-mutation.json"),
            "--out",
            str(output),
            "--metrics",
            str(metrics),
            "--charts-dir",
            str(tmp_path / "charts"),
            "--unit-evidence",
            str(unit),
            "--integration-evidence",
            str(integration),
        ],
    )

    def unavailable(*_args):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(
        mod.load_module("avo_ci_quality_dashboard", "quality_dashboard.py"),
        "render",
        unavailable,
    )
    assert mod.main() == 0
    doc = json.loads(metrics.read_text())
    measured = doc["test_evidence"]["repo-unit-tests"]
    assert measured["counts"] == {
        "total": 2,
        "passed": 1,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
    }
    assert {source["artifact"] for source in measured["sources"]} == {
        "unit-test-evidence"
    }
    assert doc["test_evidence"]["repo-integration-tests"]["counts"] is None
    assert doc["test_evidence"]["repo-integration-tests"]["state"] == "UNAVAILABLE"
    text = output.read_text()
    assert "1 passed / 0 failed / 0 errors / 1 skipped; 2 JUnit testcases" in text
    assert "0 JUnit testcases" not in text and "999" not in text
    assert "UNAVAILABLE" in text and "counts not captured" in text
    assert "Measurements remain in the table" in text
