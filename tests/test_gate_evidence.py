"""Gate receipts bind outcomes to actual command output and produced files."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
RUN_ID = "1234"


@pytest.fixture
def runner(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "quality_gate_test", ROOT / "scripts/ci/run_quality_gate.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = tmp_path
    source = tmp_path / "src/avo"
    source.mkdir(parents=True)
    (source / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    return mod


def _run(runner, code, *options):
    command = [sys.executable, "-c", code]
    status = runner.main(
        ["--gate", "lint", "--sha", SHA, "--run-id", RUN_ID, *options, "--", *command]
    )
    path = runner.ROOT / "reports/quality/gates/lint/gate.json"
    return status, path, json.loads(path.read_text()), command


def test_command_output_identity_and_hash_are_recorded(runner, capsys):
    code = "import os, sys; print('two words $literal'); print('diagnostic', file=sys.stderr); print(os.environ['AVO_QUALITY_SHA'])"
    status, path, receipt, command = _run(runner, code)
    assert status == 0
    assert receipt["command"] == command
    assert (
        receipt["sha"],
        receipt["run_id"],
        receipt["status"],
        receipt["exit_code"],
    ) == (SHA, RUN_ID, "PASS", 0)
    log = runner.ROOT / receipt["log"]["path"]
    assert receipt["log"]["sha256"] == hashlib.sha256(log.read_bytes()).hexdigest()
    assert "two words $literal" in log.read_text()
    assert "diagnostic" in log.read_text()
    assert SHA in capsys.readouterr().out
    assert receipt["duration_seconds"] >= 0
    assert receipt["source"]["unchanged"] is True
    assert receipt["source"]["start"]["files"][0]["path"] == "src/avo/sample.py"
    assert runner.validate_receipt(path, sha=SHA, run_id=RUN_ID, gate="lint")["valid"]


@pytest.mark.parametrize("code", [7, 124])
def test_nonzero_exit_and_timeout_tool_exit_are_preserved(runner, code):
    status, path, receipt, _ = _run(runner, f"import sys; sys.exit({code})")
    assert status == receipt["exit_code"] == code
    assert receipt["status"] == "FAIL"
    assert runner.validate_receipt(path, sha=SHA, run_id=RUN_ID)["valid"]


def test_artifacts_have_hashes_and_missing_output_is_explicit(runner):
    status, path, receipt, _ = _run(
        runner,
        "from pathlib import Path; Path('reports/quality/report.json').write_text('{\"value\": 2}')",
        "--artifact",
        "reports/quality/report.json",
        "--artifact",
        "reports/quality/missing.json",
    )
    assert status == 0
    present, missing = receipt["artifacts"]
    assert (
        present["sha256"]
        == hashlib.sha256((runner.ROOT / present["path"]).read_bytes()).hexdigest()
    )
    assert present["reason"] is None
    assert missing["sha256"] is None and missing["bytes"] is None
    assert missing["reason"] == "artifact was not produced"
    assert runner.validate_receipt(path, sha=SHA, run_id=RUN_ID)["valid"]


def test_unchanged_old_artifact_is_not_current_measurement(runner):
    artifact = runner.ROOT / "old.json"
    artifact.write_text("stale")
    os.utime(artifact, (1, 1))
    _, path, receipt, _ = _run(runner, "pass", "--artifact", str(artifact))
    assert receipt["artifacts"][0]["reason"] == "artifact predates command"
    assert runner.validate_receipt(path, sha=SHA, run_id=RUN_ID)["valid"]


@pytest.mark.parametrize(
    "override", [{"sha": "b" * 40}, {"run_id": "other"}, {"gate": "format"}]
)
def test_mismatched_identity_is_rejected(runner, override):
    _, path, _, _ = _run(runner, "pass")
    result = runner.validate_receipt(
        path, **{"sha": SHA, "run_id": RUN_ID, "gate": "lint", **override}
    )
    assert result["valid"] is False
    assert "mismatch" in result["reason"]


@pytest.mark.parametrize("target", ["log", "artifact"])
def test_tampered_output_is_rejected(runner, target):
    _, path, receipt, _ = _run(
        runner,
        "from pathlib import Path; Path('reports/quality/report.json').write_text('measured')",
        "--artifact",
        "reports/quality/report.json",
    )
    record = receipt["log"] if target == "log" else receipt["artifacts"][0]
    (runner.ROOT / record["path"]).write_text("tampered")
    result = runner.validate_receipt(path, sha=SHA, run_id=RUN_ID)
    assert result["valid"] is False
    assert "hash mismatch" in result["reason"]


def test_downloaded_evidence_uses_the_artifact_root(runner):
    _, path, _, _ = _run(runner, "pass")
    downloaded = runner.ROOT / "downloaded"
    shutil.copytree(runner.ROOT / "reports/quality", downloaded)
    result = runner.validate_receipt(
        path, sha=SHA, run_id=RUN_ID, artifact_root=downloaded
    )
    assert result["valid"]


@pytest.mark.parametrize(
    "bad_path",
    [
        "reports/quality/../../escape.log",
        "/outside/gate.log",
        "C:/outside/gate.log",
        "\\\\server\\outside",
        "other/gate.log",
    ],
)
def test_downloaded_evidence_cannot_escape_root(runner, bad_path):
    _, path, receipt, _ = _run(runner, "pass")
    receipt["log"]["path"] = bad_path
    path.write_text(json.dumps(receipt))
    result = runner.validate_receipt(
        path, sha=SHA, run_id=RUN_ID, artifact_root=runner.ROOT / "reports/quality"
    )
    assert not result["valid"]
    assert "path" in result["reason"]


def test_source_changes_during_command_are_recorded(runner):
    _, _, receipt, _ = _run(
        runner,
        "from pathlib import Path; Path('src/avo/sample.py').write_text('VALUE = 2\\n')",
    )
    assert not receipt["source"]["unchanged"]
    assert receipt["source"]["start"]["sha256"] != receipt["source"]["end"]["sha256"]


def test_launch_error_cannot_pass(runner):
    with mock.patch.object(
        runner.subprocess, "Popen", side_effect=OSError("tool unavailable")
    ):
        status, path, receipt, _ = _run(runner, "pass")
    assert status == 1
    assert receipt["status"] == "ERROR" and receipt["exit_code"] is None
    assert "tool unavailable" in receipt["error"]
    assert runner.validate_receipt(path, sha=SHA, run_id=RUN_ID)["valid"]


def test_child_signal_is_preserved(runner):
    proc = mock.Mock(stdout=io.BytesIO(b"terminated\n"))
    proc.wait.return_value = -15
    with mock.patch.object(runner.subprocess, "Popen", return_value=proc):
        status, _, receipt, _ = _run(runner, "pass")
    assert status == 143
    assert (receipt["status"], receipt["exit_code"], receipt["signal"]) == (
        "FAIL",
        -15,
        15,
    )


def test_wrapper_signal_records_cancellation_and_terminates_child(runner):
    proc = mock.Mock()
    proc.stdout.readline.side_effect = runner.GateInterrupted(15)
    proc.wait.return_value = -15
    with mock.patch.object(runner.subprocess, "Popen", return_value=proc):
        status, path, receipt, _ = _run(runner, "pass")
    proc.terminate.assert_called_once()
    assert status == 143
    assert (receipt["status"], receipt["exit_code"], receipt["signal"]) == (
        "CANCELLED",
        -15,
        15,
    )
    assert runner.validate_receipt(path, sha=SHA, run_id=RUN_ID)["valid"]


def test_wrapper_cancellation_is_bounded_for_unresponsive_child(runner):
    proc = mock.Mock()
    proc.stdout.readline.side_effect = KeyboardInterrupt()
    proc.wait.side_effect = [runner.subprocess.TimeoutExpired("command", 5), -9]
    with mock.patch.object(runner.subprocess, "Popen", return_value=proc):
        status, _, receipt, _ = _run(runner, "pass")
    proc.kill.assert_called_once()
    assert status == 130
    assert receipt["status"] == "CANCELLED"


def test_false_success_exit_in_receipt_is_rejected(runner):
    _, path, receipt, _ = _run(runner, "pass")
    receipt["exit_code"] = True
    path.write_text(json.dumps(receipt))
    assert not runner.validate_receipt(path, sha=SHA, run_id=RUN_ID)["valid"]
