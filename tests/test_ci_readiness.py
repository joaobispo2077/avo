from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ci/check_ci_readiness.py"
MANDATORY_JOBS = (
    "prerequisites-gate",
    "repo-unit-tests",
    "repo-integration-tests",
    "software-quality",
    "usability-gate",
    "mutation-light",
)


def load_checker():
    spec = importlib.util.spec_from_file_location("check_ci_readiness", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def successful_jobs():
    return {job: {"result": "success"} for job in MANDATORY_JOBS}


def test_every_mandatory_job_must_succeed():
    checker = load_checker()
    assert checker.evaluate_needs(successful_jobs()) == []
    for job in MANDATORY_JOBS:
        for result in ("failure", "cancelled", "skipped", "", None):
            needs = successful_jobs()
            needs[job]["result"] = result
            failures = checker.evaluate_needs(needs)
            assert len(failures) == 1
            assert job in failures[0]


def test_missing_or_malformed_mandatory_job_fails_closed():
    checker = load_checker()
    for job in MANDATORY_JOBS:
        needs = successful_jobs()
        del needs[job]
        assert job in checker.evaluate_needs(needs)[0]
        for malformed in (None, "success", [], {}):
            needs[job] = malformed
            assert job in checker.evaluate_needs(needs)[0]
    for malformed in (None, [], "success", 1):
        assert checker.evaluate_needs(malformed)


def test_selector_outputs_cannot_excuse_missing_mandatory_evidence():
    needs = successful_jobs()
    needs["select-run"] = {
        "result": "success",
        "outputs": {"run_full_ci": "false"},
    }
    needs["mutation-light"]["result"] = "skipped"
    assert "mutation-light" in load_checker().evaluate_needs(needs)[0]


@pytest.mark.parametrize("payload", ("", "not-json", "null", "[]", "{}"))
def test_cli_rejects_missing_or_invalid_evidence(payload):
    env = {**os.environ, "CI_NEEDS_JSON": payload}
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "CI readiness: FAIL" in result.stderr


def test_cli_succeeds_only_with_all_mandatory_results():
    env = {**os.environ, "CI_NEEDS_JSON": json.dumps(successful_jobs())}
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "CI readiness: PASS" in result.stdout


@pytest.mark.parametrize("ci", ("0", "1"))
def test_missing_mcp_is_optional_locally_and_a_hard_failure_in_ci(ci):
    code = """
import importlib.abc
import runpy
import sys

class MissingMCP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp."):
            raise ModuleNotFoundError("MCP deliberately unavailable", name="mcp")

sys.meta_path.insert(0, MissingMCP())
runpy.run_path(sys.argv[1])
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(ROOT / "tests/integration/test_avo_mcp_stdio.py"),
        ],
        env={**os.environ, "AVO_CI": ci},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    if ci == "1":
        assert "ModuleNotFoundError: MCP deliberately unavailable" in result.stderr
        assert "Skipped:" not in result.stderr
    else:
        assert "Skipped: could not import 'mcp'" in result.stderr


def test_workflow_wires_readiness_after_all_mandatory_jobs():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    readiness = workflow.split("  ci-readiness:\n", 1)[1]
    assert "name: CI readiness" in readiness
    configuration = readiness.split("    steps:\n", 1)[0]
    assert "!cancelled()" in configuration
    assert (
        "!(needs.select-run.result == 'success' && "
        "needs.select-run.outputs.run_full_ci == 'false')"
    ) in configuration
    needs = readiness.split("    needs:\n", 1)[1].split("    runs-on:", 1)[0]
    assert {line.strip()[2:] for line in needs.splitlines()} == {
        "select-run",
        *MANDATORY_JOBS,
    }
    assert "CI_NEEDS_JSON: ${{ toJSON(needs) }}" in readiness
    assert "run: python scripts/ci/check_ci_readiness.py" in readiness
    integration = workflow.split("  repo-integration-tests:\n", 1)[1].split(
        "  software-quality:\n", 1
    )[0]
    assert "uv sync --frozen --extra dev --extra mcp" in integration
    pr = workflow.split("  pull_request:\n", 1)[1].split("\nenv:", 1)[0]
    assert "      - develop" in pr
