"""Queue decisions share bounded native/engine/MCP behavior without media setup."""

import json

import pytest

from avo.mcp.bridge import run_bridged, run_cli
from avo.mcp.tools.cli_tools import all_bridge_defs
from tests.test_craft_work_decisions import decision, pending


def definition():
    return next(
        tool
        for tool in all_bridge_defs()
        if tool.spec.name == "avo_pipeline_work_decide"
    )


def test_native_engine_and_mcp_share_reversible_work_decisions_without_media_setup(
    tmp_path, monkeypatch, capsys
):
    from avo import cli, engine_cli

    workspace, _, _, row = pending(tmp_path)
    path = tmp_path / "defer.json"
    path.write_text(json.dumps(decision(row, "deferred")), encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("A work-queue decision constructed motion execution")

    monkeypatch.setattr(cli, "create_motion_materializer", forbidden)
    args = [
        "pipeline",
        "work-decide",
        "--project",
        str(workspace.project_path),
        "--video-id",
        workspace.video_id,
        "--request",
        str(path),
        "--json",
    ]
    native = run_cli(args)
    assert native.exit_code == 0, native.stderr
    assert native.parsed_json["effect"] == "request-decision-write"
    tool = definition()
    assert tool.spec.destructive is False
    bridged = run_bridged(
        tool.cli_prefix,
        {
            "project": str(workspace.project_path),
            "video_id": workspace.video_id,
            "request": str(path),
        },
    )
    assert bridged.exit_code == 0, bridged.stderr
    assert bridged.parsed_json["decision"] == native.parsed_json["decision"]
    assert bridged.parsed_json["status"] == "replayed"
    assert engine_cli.main(["cli", *args]) == 0
    assert (
        json.loads(capsys.readouterr().out)["decision"]
        == native.parsed_json["decision"]
    )


@pytest.mark.parametrize("problem", ["duplicate", "budget", "digest"])
def test_invalid_work_decision_is_rejected_before_project_access(
    tmp_path, monkeypatch, problem
):
    from avo.editing_craft_requests import MAX_REQUEST_BYTES
    from avo.timeline.workspace import TimelineWorkspace

    path = tmp_path / "invalid.json"
    path.write_text(
        '{"operation":"work-decide","operation":"work-decide"}', encoding="utf-8"
    )
    expected = "Duplicate request property"
    extra = []
    if problem == "budget":
        path.write_bytes(b" " * (MAX_REQUEST_BYTES + 1))
        expected = "1 MiB input budget"
    elif problem == "digest":
        path.write_text("{}", encoding="utf-8")
        extra = ["--request-sha256", "f" * 64]
        expected = "changed after confirmation"

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid decision accessed its project")

    monkeypatch.setattr(TimelineWorkspace, "from_project", forbidden)
    result = run_cli(
        [
            "pipeline",
            "work-decide",
            "--project",
            str(tmp_path / "missing.json"),
            "--request",
            str(path),
            "--json",
            *extra,
        ]
    )
    assert result.exit_code == 2
    assert expected in result.stderr


def test_presentation_failure_preserves_the_recorded_request_decision(
    tmp_path, monkeypatch
):
    from avo import motion_plan_cli
    from tests.integration.test_editing_craft_resume import fresh_map

    workspace, _, _, row = pending(tmp_path)
    path = tmp_path / "dismiss.json"
    path.write_text(json.dumps(decision(row, "dismissed")), encoding="utf-8")
    monkeypatch.setattr(
        motion_plan_cli,
        "publish_after_authoring",
        lambda _: {
            "reviewReady": False,
            "warnings": ["fixture report publication unavailable"],
        },
    )
    result = run_cli(
        [
            "pipeline",
            "work-decide",
            "--project",
            str(workspace.project_path),
            "--video-id",
            workspace.video_id,
            "--request",
            str(path),
            "--json",
        ]
    )
    assert result.exit_code == 0, result.stderr
    assert result.parsed_json["reviewReady"] is False
    assert fresh_map(workspace)["pendingRevisions"][0]["status"] == "dismissed"
