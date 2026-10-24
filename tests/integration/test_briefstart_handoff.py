import pytest
from tests.test_briefstart_context import project_fixture, selected_project

from avo.direction.rules import DirectionError
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.workspace import TimelineWorkspace


def test_real_coordinator_offers_exact_selected_brief_without_a_second_pointer(
    tmp_path,
):
    project, _, brief_ref, _ = selected_project(tmp_path)
    workspace = TimelineWorkspace.from_project(project)
    pipeline = TimelinePipeline(workspace)
    before = (project.parent / "edit/briefstart/index.json").read_bytes()
    status = pipeline.status()
    assert status["briefing"]["refs"]["brief"] == brief_ref
    for stage in ("structure", "cmap", "bmap", "motion", "sound"):
        offered = pipeline.authoring_context(stage)
        assert offered["context"]["briefRef"] == brief_ref
        assert status["briefing"]["stageContexts"][stage] == offered
        assert offered["context"]["treatment"]["rhythm"] == "Natural pauses"
    assert (project.parent / "edit/briefstart/index.json").read_bytes() == before
    assert not workspace.pipeline_run_path.exists()


def test_real_raw_coordinator_has_no_history_or_briefing_writes(tmp_path, monkeypatch):
    project = project_fixture(tmp_path)
    workspace = TimelineWorkspace.from_project(project)
    monkeypatch.setattr(
        workspace,
        "finalized_provider_learning",
        lambda: (_ for _ in ()).throw(AssertionError("history accessed")),
    )
    result = TimelinePipeline(workspace).status()
    assert result["briefing"]["status"] == "bypassed"
    assert result["briefing"]["stageContexts"] == {}
    assert not (project.parent / "edit").exists()


def test_selected_brief_cannot_cross_the_explicit_workspace_video_identity(tmp_path):
    project, _, _, _ = selected_project(tmp_path)
    workspace = TimelineWorkspace.from_project(project, video_id="another-video")
    with pytest.raises(DirectionError, match="identity"):
        TimelinePipeline(workspace).authoring_context("motion")


def test_raw_bypass_still_supports_an_explicit_workspace_video_identity(tmp_path):
    project = project_fixture(tmp_path)
    workspace = TimelineWorkspace.from_project(project, video_id="another-video")
    assert TimelinePipeline(workspace).status()["briefing"]["status"] == "bypassed"
