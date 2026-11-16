"""Native/MCP motion inspection and explicit derived-report publication."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.mcp.bridge import run_bridged, run_cli


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    raw = tmp_path / "clip"
    raw.mkdir()
    manifest = raw / "avo.project.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "example",
                "videoId": "clip",
                "rawDir": str(raw),
            }
        ),
        encoding="utf-8",
    )
    return manifest


def definition(operation):
    from avo.mcp.tools.cli_tools import all_bridge_defs

    return next(
        item
        for item in all_bridge_defs()
        if item.spec.name == "avo_animation_" + operation.replace("-", "_")
    )


def test_plan_show_is_available_without_optional_tools_or_canonical_state(project):
    before = {p: p.read_bytes() for p in project.parent.rglob("*") if p.is_file()}
    result = run_cli(["animation", "plan-show", "--project", str(project), "--json"])
    assert result.exit_code == 0, result.stderr
    assert result.parsed_json["effect"] == "metadata-read"
    assert result.parsed_json["snapshot"]["basisHeads"] == {
        key: None for key in ("cmap", "bmap", "tracks", "animation", "sync-map")
    }
    assert {
        p: p.read_bytes() for p in project.parent.rglob("*") if p.is_file()
    } == before


def test_only_explicit_publish_creates_current_report_and_not_canonical_state(project):
    shown = run_cli(["animation", "plan-show", "--project", str(project), "--json"])
    assert shown.exit_code == 0, shown.stderr
    published = run_cli(
        ["animation", "plan-publish", "--project", str(project), "--json"]
    )
    assert published.exit_code == 0, published.stderr
    assert published.parsed_json["effect"] == "derived-write"
    again = run_cli(["animation", "plan-show", "--project", str(project), "--json"])
    assert again.exit_code == 0, again.stderr
    assert again.parsed_json["snapshot"] == shown.parsed_json["snapshot"]
    assert again.parsed_json["report"]["freshness"] == "current"
    assert not list((project.parent / "edit/timeline").glob("*/index.json"))


@pytest.mark.parametrize("operation", ["plan-show", "plan-publish"])
def test_mcp_and_native_share_exact_operation(project, operation):
    tool = definition(operation)
    result = run_bridged(tool.cli_prefix, {"project": str(project)})
    assert result.exit_code == 0, result.stderr
    assert result.parsed_json["operation"] == operation
    assert result.parsed_json["effect"] == (
        "metadata-read" if operation == "plan-show" else "derived-write"
    )


def test_plan_commands_reject_relative_manifest_before_execution():
    result = run_cli(["animation", "plan-show", "--project", "relative.json", "--json"])
    assert result.exit_code != 0
    assert "absolute" in result.stderr


@pytest.mark.parametrize("publish_fails", [False, True])
def test_motion_authoring_publishes_review_after_commit_without_rolling_it_back(
    project, monkeypatch, publish_fails
):
    from avo import cli, motion
    from avo.timeline.animation import AnimationService
    from avo.timeline.pipeline import TimelinePipeline
    from avo.timeline.workspace import TimelineWorkspace

    workspace = TimelineWorkspace.from_project(project)
    events = []
    monkeypatch.setattr(cli, "_load_json", lambda _: {"framework": "hyperframes"})
    monkeypatch.setattr(TimelineWorkspace, "from_project", lambda *a, **k: workspace)
    monkeypatch.setattr(motion, "inspect_motion", lambda **k: {"selection": {}})

    def author(*args, **kwargs):
        events.append("canonical-commit")
        return {"revisionId": "animation-r1"}

    def publish(*args, **kwargs):
        assert events == ["canonical-commit"]
        events.append("review-publication")
        if publish_fails:
            raise OSError("Review directory unavailable")
        return {"freshness": "current", "refs": {}}

    monkeypatch.setattr(AnimationService, "author", author)
    monkeypatch.setattr(TimelinePipeline, "publish_motion_plan", publish)
    result = cli._author_animation(
        SimpleNamespace(
            strategy=project,
            project=project,
            video_id=None,
            motion_engine=None,
            actor="creator",
            reason="Selected motion",
        )
    )
    assert events == ["canonical-commit", "review-publication"]
    assert result["revisionId"] == "animation-r1"
    assert result["motionPlanReport"]["freshness"] == (
        "unavailable" if publish_fails else "current"
    )
