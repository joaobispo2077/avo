from __future__ import annotations

import json
from pathlib import Path

from avo.cli import main
from tests.integration.test_timeline_migration_runtime import fixture


def test_migration_cli_full_state_and_rollback(tmp_path: Path, capsys):
    workspace, edl, project = fixture(tmp_path)
    common = ["--project", str(project), "--edl", str(edl)]

    assert main(["migrate-timeline", "plan", *common]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dryRun"] is True
    assert not workspace.timeline_dir.exists()

    assert main([
        "migrate-timeline", "apply", *common,
        "--actor", "creator", "--reason", "apply",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "applied-unverified"
    assert main([
        "migrate-timeline", "validate", *common,
        "--actor", "creator", "--reason", "parity",
    ]) == 0
    capsys.readouterr()
    assert main([
        "migrate-timeline", "activate", *common,
        "--actor", "creator", "--reason", "activate",
        "--confirm-unknown-approvals",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["authority"] == "canonical"
    assert main([
        "migrate-timeline", "rollback", *common,
        "--actor", "creator", "--reason", "rollback",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "rolled-back"
