"""Scope inspection is bounded, shared across entrypoints and metadata-only."""

import json

import pytest

from avo.mcp.bridge import run_bridged, run_cli
from avo.mcp.tools.cli_tools import all_bridge_defs
from tests.test_sound_proposals import prepared


def scope_request():
    return {
        "clock": {"frameRate": {"num": 24, "den": 1}, "programEndFrame": 24},
        "chunks": [
            {"chunkId": "opening", "startFrame": 0, "endFrameExclusive": 6},
            {"chunkId": "later", "startFrame": 6, "endFrameExclusive": 24},
        ],
        "selectedChunkIds": ["later"],
    }


def test_native_engine_and_mcp_show_the_same_exact_scope_without_media_setup(
    tmp_path, monkeypatch, capsys
):
    from avo import cli, engine_cli

    workspace, _, _ = prepared(tmp_path)
    path = tmp_path / "scope-request.json"
    path.write_text(json.dumps(scope_request()), encoding="utf-8")
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("Scope inspection constructed a media runtime")

    monkeypatch.setattr(cli, "create_motion_materializer", forbidden)
    args = [
        "animation",
        "plan-show",
        "--project",
        str(workspace.project_path),
        "--video-id",
        workspace.video_id,
        "--scope-request",
        str(path),
        "--json",
    ]
    native = run_cli(args)
    assert native.exit_code == 0, native.stderr
    scope = native.parsed_json["snapshot"]["productionScope"]
    assert scope["production"] == []
    assert [row["itemId"] for row in scope["context"]] == ["mo04"]
    assert scope["context"][0]["ownerChunkId"] == "opening"
    tool = next(
        tool
        for tool in all_bridge_defs()
        if tool.spec.name == "avo_animation_plan_show"
    )
    bridged = run_bridged(
        tool.cli_prefix,
        {
            "project": str(workspace.project_path),
            "video_id": workspace.video_id,
            "scope_request": str(path),
        },
    )
    assert bridged.exit_code == 0, bridged.stderr
    assert bridged.parsed_json["snapshot"] == native.parsed_json["snapshot"]
    assert engine_cli.main(["cli", *args]) == 0
    assert (
        json.loads(capsys.readouterr().out)["snapshot"]
        == native.parsed_json["snapshot"]
    )
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize("problem", ["duplicate", "budget", "invalid"])
def test_bad_scope_request_is_rejected_before_project_access(
    tmp_path, monkeypatch, problem
):
    from avo.editing_craft_requests import MAX_REQUEST_BYTES
    from avo.timeline.workspace import TimelineWorkspace

    path = tmp_path / "bad-scope.json"
    path.write_text('{"chunks":[],"chunks":[]}', encoding="utf-8")
    if problem == "budget":
        path.write_bytes(b" " * (MAX_REQUEST_BYTES + 1))
    elif problem == "invalid":
        path.write_text("{}", encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid scope accessed the project")

    monkeypatch.setattr(TimelineWorkspace, "from_project", forbidden)
    result = run_cli(
        [
            "animation",
            "plan-show",
            "--project",
            str(tmp_path / "missing.json"),
            "--scope-request",
            str(path),
            "--json",
        ]
    )
    assert result.exit_code == 2
    assert json.loads(result.stderr)["code"] == "MOTION_REVIEW_UNAVAILABLE"


def test_scope_publication_exposes_text_and_visual_ownership_and_no_approval(tmp_path):
    workspace, _, _ = prepared(tmp_path)
    path = tmp_path / "scope-request.json"
    path.write_text(json.dumps(scope_request()), encoding="utf-8")
    result = run_cli(
        [
            "animation",
            "plan-publish",
            "--project",
            str(workspace.project_path),
            "--scope-request",
            str(path),
            "--json",
        ]
    )
    assert result.exit_code == 0, result.stderr
    from avo.timeline.motion_review import render_html, render_text
    from avo.timeline.pipeline import TimelinePipeline

    snapshot = TimelinePipeline(workspace).motion_plan(scope_request=scope_request())
    for rendered in (render_text(snapshot), render_html(snapshot)):
        assert "later" in rendered
        assert "opening" in rendered
        assert "mo04" in rendered
        assert "context" in rendered.lower()
        assert "No approval" in rendered
