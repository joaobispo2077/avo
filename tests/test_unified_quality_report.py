"""Unification must reject stale evidence and retain text after image failures."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
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
    count_lines = "\n".join(
        line
        for line in text.splitlines()
        if line.startswith(
            (
                "| repo-unit-tests |",
                "| repo-integration-tests |",
                "- repo-unit-tests:",
                "- repo-integration-tests:",
            )
        )
    )
    assert (
        "1 passed / 0 failed / 0 errors / 1 skipped; 2 JUnit testcases." in count_lines
    )
    assert (
        "1 passed / 0 failed / 0 errors / 1 skipped; 2 testcase events." in count_lines
    )
    assert "Job result; testcase counts not captured." in count_lines
    assert "Testcase counts unavailable." in count_lines
    assert "0 JUnit testcases" not in text
    # 999 is the fixture sentinel. Match it only as its own count so a SHA,
    # SHA-256, or GitHub run/commit URL that happens to contain those digits
    # cannot fail or satisfy the check.
    report = re.sub(r"https://github\.com/\S+", "", text)
    assert re.search(r"(?<![0-9A-Fa-f])999(?![0-9A-Fa-f])", report) is None
    assert "UNAVAILABLE" in text and "counts not captured" in text
    assert "Dashboard image unavailable; current measurements remain in text." in text


def pr_environment(tmp_path, monkeypatch, *, attempt="2"):
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "number": 100,
                "pull_request": {
                    "head": {"sha": "b" * 40},
                    "base": {"sha": "c" * 40},
                },
            }
        ),
        encoding="utf-8",
    )
    for key, value in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": "42",
        "GITHUB_RUN_ATTEMPT": attempt,
        "GITHUB_REPOSITORY": "owner/avo",
    }.items():
        monkeypatch.setenv(key, value)


def test_writer_captures_event_context_without_replacing_tested_merge(
    tmp_path, monkeypatch
):
    pr_environment(tmp_path, monkeypatch)
    doc = load().combine(evidence(tmp_path), None, sha=SHA, run_id="42", needs={})
    assert doc["sha"] == SHA
    assert doc["run_id"] == "42"
    assert doc["reporting"] == {
        "schema": 1,
        "mode": "ci",
        "pr_number": 100,
        "head_sha": "b" * 40,
        "base_sha": "c" * 40,
        "run_attempt": 2,
    }
    assert doc["repository"] == "owner/avo"


@pytest.mark.parametrize(
    "reporting",
    [
        {"schema": 1, "mode": "fixture"},
        {"schema": 99, "mode": "ci"},
        {"schema": 1, "mode": "ci", "run_id": "different-run"},
    ],
)
def test_writer_cannot_promote_invalid_or_preview_evidence_to_current_ci(
    tmp_path, monkeypatch, reporting
):
    pr_environment(tmp_path, monkeypatch)
    path = evidence(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["reporting"] = reporting
    path.write_text(json.dumps(payload), encoding="utf-8")
    doc = load().combine(path, None, sha=SHA, run_id="42", needs={})
    assert doc["overall"] != "PASS"
    assert doc["series"]["dashboard"]["metrics"][0]["measured"] is None


@pytest.mark.parametrize(
    "job",
    [
        "prerequisites-gate",
        "repo-unit-tests",
        "repo-integration-tests",
        "software-quality",
        "usability-gate",
        "mutation-light",
    ],
)
@pytest.mark.parametrize("result", ["failure", "skipped", "cancelled", "unknown"])
def test_each_unsuccessful_required_job_retains_report_and_action(
    tmp_path, job, result
):
    mod = load()
    needs = {
        name: {"result": "success"}
        for name in (*mod.readiness().MANDATORY_JOBS, "ci-readiness")
    }
    needs[job] = {"result": result}
    doc = mod.combine(evidence(tmp_path), None, sha=SHA, run_id="42", needs=needs)
    dashboard = mod.load_module("avo_ci_quality_dashboard", "quality_dashboard.py")
    text = dashboard.markdown(doc, doc["series"]["dashboard"])
    assert doc["overall"] != "PASS"
    assert doc["jobs"][job] == result
    assert job in text
    assert any(job in action for action in doc["series"]["dashboard"]["actions"])


@pytest.mark.parametrize("result", ["failure", "skipped", "cancelled", "unknown"])
def test_fatal_builder_fallback_is_dependency_isolated_and_markdown_only(
    tmp_path, monkeypatch, result
):
    import sys

    mod = load()
    pr_environment(tmp_path, monkeypatch)
    original_loader = mod.load_module
    loaded = []

    def isolated_loader(name, filename):
        loaded.append(filename)
        if filename != "check_ci_readiness.py":
            raise ImportError("normalization and rendering deliberately unavailable")
        return original_loader(name, filename)

    monkeypatch.setattr(mod, "load_module", isolated_loader)
    monkeypatch.setenv(
        "CI_NEEDS_JSON",
        json.dumps({"repo-integration-tests": {"result": result}}),
    )
    output = tmp_path / "fallback" / "report.md"
    metrics = tmp_path / "must-not-touch.json"
    metrics.write_text('{"previous":"partial"}', encoding="utf-8")
    charts = tmp_path / "charts"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "write_unified_quality_report.py",
            "--text-only-fallback",
            "--out",
            str(output),
            "--metrics",
            str(metrics),
            "--charts-dir",
            str(charts),
        ],
    )
    assert mod.main() == 0
    text = output.read_text(encoding="utf-8")
    assert "Overall: FAIL" in text
    assert "report builder failed" in text.lower()
    assert f"| repo-integration-tests | {result.upper()} |" in text
    assert SHA in text and "b" * 40 in text and "c" * 40 in text
    assert (
        "Run: [42](https://github.com/owner/avo/actions/runs/42/attempts/2) · Attempt: 2"
        in text
    )
    assert "Unavailable" in text and "Overall: PASS" not in text
    assert "kpi-chart:" not in text and "![" not in text
    assert metrics.read_text(encoding="utf-8") == '{"previous":"partial"}'
    assert not charts.exists()
    assert set(loaded) <= {"check_ci_readiness.py"}


def test_fallback_does_not_claim_green_when_every_mandatory_job_passed(
    tmp_path, monkeypatch
):
    import sys

    mod = load()
    pr_environment(tmp_path, monkeypatch, attempt="not-an-attempt")
    monkeypatch.setenv(
        "CI_NEEDS_JSON",
        json.dumps(
            {
                name: {"result": "success"}
                for name in (*mod.readiness().MANDATORY_JOBS, "ci-readiness")
            }
        ),
    )
    output = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        ["writer", "--text-only-fallback", "--out", str(output)],
    )
    assert mod.main() == 0
    text = output.read_text(encoding="utf-8")
    assert "Overall: FAIL" in text and "Overall: PASS" not in text
    assert "Attempt: Unavailable" in text


@pytest.mark.parametrize("needs", ["not json", "[]", "null", "{}"])
def test_fallback_local_identity_and_malformed_jobs_remain_unavailable(
    tmp_path, monkeypatch, needs
):
    import sys

    for name in (
        "GITHUB_ACTIONS",
        "GITHUB_EVENT_NAME",
        "GITHUB_EVENT_PATH",
        "GITHUB_REPOSITORY",
        "GITHUB_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CI_NEEDS_JSON", needs)
    output = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        ["writer", "--text-only-fallback", "--out", str(output)],
    )
    assert load().main() == 0
    text = output.read_text(encoding="utf-8")
    assert "Local preview" in text
    assert "Tested revision: Unavailable" in text
    assert "| repo-integration-tests | UNKNOWN |" in text
    assert "https://github.com" not in text
