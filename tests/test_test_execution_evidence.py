from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
RUN_ID = "42"
GATE = "unit-tests"
ARTIFACT = "unit-test-evidence"
JUNIT = "unit-tests.xml"


def reader():
    spec = importlib.util.spec_from_file_location(
        "test_execution_evidence", ROOT / "scripts/ci/test_execution_evidence.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(directory, xml, *, status="PASS", code=0):
    gate_dir = directory / "gates" / GATE
    gate_dir.mkdir(parents=True)
    log = gate_dir / "gate.log"
    log.write_bytes(b"Test runner captured output.\n")
    junit = directory / JUNIT
    junit.write_bytes(xml.encode("utf-8") if isinstance(xml, str) else xml)

    def record(path):
        raw = path.read_bytes()
        return {
            "path": "reports/quality/" + path.relative_to(directory).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "reason": None,
        }

    receipt = {
        "schema_version": 1,
        "sha": SHA,
        "run_id": RUN_ID,
        "gate": GATE,
        "status": status,
        "exit_code": code,
        "log": record(log),
        "artifacts": [record(junit)],
    }
    receipt_path = gate_dir / "gate.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return receipt_path, receipt, junit, log


def evidence(directory):
    return reader().read_test_evidence(
        directory,
        sha=SHA,
        run_id=RUN_ID,
        gate=GATE,
        artifact=ARTIFACT,
        junit_name=JUNIT,
    )


def test_actual_testcase_events_are_counted_once_across_nested_suites(tmp_path):
    fixture(
        tmp_path,
        """<testsuites tests="999" failures="999">
      <testsuite tests="999"><testcase name="pass"/>
        <testsuite><testcase name="failure"><failure/><failure/></testcase>
        <testcase name="error"><error/></testcase></testsuite>
        <testcase name="skip"><skipped/></testcase>
      </testsuite><testsuite><testcase name="other-pass"/></testsuite>
    </testsuites>""",
        status="FAIL",
        code=1,
    )
    result = evidence(tmp_path)
    assert result["state"] == "PARTIAL"
    assert result["counts"] == {
        "total": 5,
        "passed": 2,
        "failed": 1,
        "errors": 1,
        "skipped": 1,
    }
    assert result["counts"]["total"] == sum(
        value for key, value in result["counts"].items() if key != "total"
    )
    assert {source["path"] for source in result["sources"]} == {
        JUNIT,
        f"gates/{GATE}/gate.log",
    }
    assert all(
        source["artifact"] == ARTIFACT and len(source["sha256"]) == 64
        for source in result["sources"]
    )


def test_successful_suite_and_skip_counts_are_measured_not_inferred_from_job(tmp_path):
    fixture(
        tmp_path,
        '<testsuite><testcase name="one"/><testcase name="skip"><skipped/></testcase></testsuite>',
    )
    result = evidence(tmp_path)
    assert result["state"] == "MEASURED"
    assert result["counts"] == {
        "total": 2,
        "passed": 1,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
    }


@pytest.mark.parametrize(
    "status,code", (("FAIL", 1), ("ERROR", None), ("CANCELLED", -15))
)
def test_available_xml_on_unsuccessful_execution_is_partial(tmp_path, status, code):
    fixture(
        tmp_path,
        '<testsuite><testcase name="observed"/></testsuite>',
        status=status,
        code=code,
    )
    result = evidence(tmp_path)
    assert result["state"] == "PARTIAL"
    assert result["counts"]["passed"] == 1
    assert status in result["reason"]


def test_subtest_failures_within_one_case_are_one_failed_case(tmp_path):
    fixture(
        tmp_path,
        """<testsuite tests="4" failures="3">
      <testcase name="subtests"><failure message="subtest-a"/><failure message="subtest-b"/>
      <failure message="subtest-c"/></testcase><testcase name="next"/>
    </testsuite>""",
        status="FAIL",
        code=1,
    )
    result = evidence(tmp_path)
    assert result["counts"] == {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "errors": 0,
        "skipped": 0,
    }


@pytest.mark.parametrize(
    "body", ("<failure/><skipped/>", "<error/><failure/>", "<skipped/><error/>")
)
def test_conflicting_case_outcomes_cannot_publish_counts(tmp_path, body):
    fixture(
        tmp_path, f'<testsuite><testcase name="conflict">{body}</testcase></testsuite>'
    )
    result = evidence(tmp_path)
    assert result["state"] == "UNAVAILABLE"
    assert result["counts"] is None
    assert "conflicting" in result["reason"]


@pytest.mark.parametrize(
    "problem",
    (
        "wrong-run",
        "wrong-gate",
        "junit-tamper",
        "log-tamper",
        "stale",
        "missing-xml",
        "path",
    ),
)
def test_untrusted_execution_artifacts_never_supply_counts(tmp_path, problem):
    path, receipt, junit, log = fixture(
        tmp_path, '<testsuite><testcase name="one"/></testsuite>'
    )
    if problem == "wrong-run":
        receipt["run_id"] = "another-run"
    elif problem == "wrong-gate":
        receipt["gate"] = "integration-tests"
    elif problem == "junit-tamper":
        junit.write_bytes(b"<testsuite><testcase/></testsuite>")
    elif problem == "log-tamper":
        log.write_bytes(b"Changed log")
    elif problem == "stale":
        receipt["artifacts"][0]["reason"] = "artifact predates command"
    elif problem == "missing-xml":
        junit.unlink()
    else:
        receipt["artifacts"][0]["path"] = "reports/quality/../../outside.xml"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    result = evidence(tmp_path)
    assert result["state"] == "UNAVAILABLE"
    assert result["counts"] is None
    assert result["reason"]


@pytest.mark.parametrize("encoding", ("utf-8", "utf-16"))
def test_dtd_and_external_entities_are_refused_in_any_supported_encoding(
    tmp_path, encoding
):
    xml = f'''<?xml version="1.0" encoding="{encoding}"?>
    <!DOCTYPE testsuite [<!ENTITY injected SYSTEM "file:///private.txt">]>
    <testsuite><testcase name="&injected;"/></testsuite>'''
    fixture(tmp_path, xml.encode(encoding))
    result = evidence(tmp_path)
    assert result["counts"] is None
    assert result["state"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    "xml",
    (
        "<testsuite",
        "<other><testcase/></other>",
        "<testsuite><properties><testcase/></properties></testsuite>",
    ),
)
def test_malformed_or_non_junit_xml_is_unavailable(tmp_path, xml):
    fixture(tmp_path, xml)
    result = evidence(tmp_path)
    assert result["counts"] is None
    assert result["state"] == "UNAVAILABLE"


def test_empty_suite_is_partial_and_does_not_claim_passed_tests(tmp_path):
    fixture(tmp_path, "<testsuites/>")
    result = evidence(tmp_path)
    assert result["state"] == "PARTIAL"
    assert result["counts"] == {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
    }


def test_contradictory_passing_receipt_keeps_actual_failures_visible(tmp_path):
    fixture(
        tmp_path, '<testsuite><testcase name="one"><failure/></testcase></testsuite>'
    )
    result = evidence(tmp_path)
    assert result["state"] == "PARTIAL"
    assert result["counts"]["failed"] == 1


def test_absent_receipt_is_unavailable(tmp_path):
    result = evidence(tmp_path)
    assert result["counts"] is None
    assert result["state"] == "UNAVAILABLE"
