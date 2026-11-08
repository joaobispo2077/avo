"""Pipeline import convenience preserves canonical editing and review authority."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.import_service import TimelineImportService
from avo.timeline.otio_import import ImportError
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.workspace import TimelineWorkspace
from tests.test_timeline_import_service import (
    FIXTURE,
    _approve_fixture_sync,
    _probe,
    _trial,
)
from tests.test_timeline_import_service import (
    import_project as _import_project,
)


@pytest.fixture(name="import_project")
def import_project_fixture(tmp_path):
    return _import_project.__wrapped__(tmp_path)


def _fake_service(workspace, result):
    return SimpleNamespace(
        workspace=workspace,
        provider=workspace.project["provider"],
        root=(workspace.timeline_dir / "imports").resolve(),
        prepare=Mock(return_value={"importId": "a" * 64}),
        validate=Mock(return_value=result),
        activate=Mock(side_effect=AssertionError("Never auto-activate an import")),
    )


def test_pipeline_import_only_prepares_validates_and_preserves_result(
    import_project, monkeypatch
):
    project, _, original = import_project
    workspace = TimelineWorkspace.from_project(project)
    pipeline = TimelinePipeline(workspace)
    result = {
        "status": "awaiting-sync",
        "importId": "a" * 64,
        "validationHash": "b" * 64,
        "readiness": {"activationAllowed": False, "syncReady": "failed"},
        "nextAction": "Complete this exact fixture's Sync/N/A review",
    }
    before = deepcopy(result)
    service = _fake_service(workspace, result)
    monkeypatch.setattr(
        pipeline, "initialize", Mock(side_effect=AssertionError("No initialization"))
    )
    monkeypatch.setattr(
        pipeline, "briefing_status", Mock(side_effect=AssertionError("No briefing"))
    )
    monkeypatch.setattr(
        pipeline.run_store,
        "bind_motion_selection",
        Mock(side_effect=AssertionError("No motion choice")),
    )
    mappings = {"/clip": {"path": str(original)}}
    declarations = {"sourceOnly": True}
    path = project.parent / "export.otio"
    shown = pipeline.prepare_timeline_import(
        service,
        path,
        timeline="/timelines/0",
        media_roots=[original.parent],
        mappings=mappings,
        declarations=declarations,
        actor="editor",
        reason="Continue supplied edit",
    )
    service.prepare.assert_called_once_with(
        path,
        timeline="/timelines/0",
        media_roots=[original.parent],
        mappings=mappings,
        declarations=declarations,
        actor="editor",
        reason="Continue supplied edit",
    )
    service.validate.assert_called_once_with("a" * 64)
    service.activate.assert_not_called()
    assert shown == {**before, "pipelineAction": "timeline-import"}
    assert result == before
    assert not workspace.artifact_path("cmap").exists()
    assert not workspace.pipeline_run_path.exists()


@pytest.mark.parametrize(
    "defect",
    [
        "project",
        "provider",
        "workspace-provider",
        "video",
        "raw",
        "timeline",
        "imports",
    ],
)
def test_pipeline_import_rejects_wrong_target_before_staging(import_project, defect):
    project, _, _ = import_project
    workspace = TimelineWorkspace.from_project(project)
    other = TimelineWorkspace.from_project(project)
    service = _fake_service(other, {"status": "blocked", "importId": "a" * 64})
    if defect == "project":
        other.project_path = project.parent / "different.project.json"
    elif defect == "provider":
        service.provider = "another-channel"
    elif defect == "workspace-provider":
        other.project = {**other.project, "provider": "another-channel"}
    elif defect == "video":
        other.video_id = "another-video"
    elif defect == "raw":
        other.raw_dir = project.parent / "another-video"
    elif defect == "timeline":
        other.timeline_dir = project.parent / "elsewhere"
    else:
        service.root = project.parent / "elsewhere"
    with pytest.raises(ImportError) as error:
        TimelinePipeline(workspace).prepare_timeline_import(
            service,
            project.parent / "export.otio",
            actor="editor",
            reason="Stage export",
        )
    assert error.value.code == "OTIO_TARGET_CONFLICT"
    service.prepare.assert_not_called()
    service.validate.assert_not_called()
    service.activate.assert_not_called()


@pytest.mark.parametrize("status", ["blocked", "awaiting-sync", "ready-to-activate"])
def test_pipeline_import_adds_action_without_changing_readiness(import_project, status):
    project, _, _ = import_project
    workspace = TimelineWorkspace.from_project(project)
    readiness = {"activationAllowed": status == "ready-to-activate"}
    service = _fake_service(
        workspace,
        {"status": status, "importId": "a" * 64, "readiness": readiness},
    )
    result = TimelinePipeline(workspace).prepare_timeline_import(
        service, project.parent / "export.otio", actor="editor", reason="Stage export"
    )
    assert result["status"] == status
    assert result["readiness"] == readiness
    assert result["nextAction"]
    assert result["pipelineAction"] == "timeline-import"
    service.activate.assert_not_called()


def test_pipeline_status_resume_and_ordinary_initialize_keep_imported_draft(
    import_project,
):
    # Synthetic probe and fixture-only Sync approval do not prove native fidelity.
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = _trial(service, original)
    waiting = service.validate(prepared["importId"])
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture-editor",
        reason="Select synthetic imported draft",
    )
    pipeline = TimelinePipeline(service.workspace)
    pipeline.run_store.bind_motion_selection(
        {
            "engine": "code-drawn",
            "source": "invocation",
            "advanced": True,
            "resolutionHash": "c" * 64,
            "maskedChoices": [],
        }
    )
    store = service.workspace.store("cmap")
    before = store.load()
    motion = deepcopy(pipeline.run_store.load()["executionChoices"]["motion"])
    status = pipeline.status()
    assert status["timelineImport"]["originRef"]["importId"] == prepared["importId"]
    pipeline.enter_blocked(reason="Await review", blockers=[])
    restarted = TimelinePipeline(TimelineWorkspace.from_project(project))
    resumed = restarted.resume(
        actor="fixture-editor",
        reason="Review available",
        recovery_event="review-ready",
    )
    assert resumed["mainState"] == "cmap-draft"
    assert resumed["sideState"] is None
    after = restarted.initialize()
    assert after["timelineImport"]["originRef"] == status["timelineImport"]["originRef"]
    assert store.load() == before
    assert store.effective_approval() is None
    assert restarted.run_store.load()["executionChoices"]["motion"] == motion
    assert service.workspace.store("bmap").load_index()["headRevisionId"] is None


def test_pipeline_real_staging_never_infers_missing_import_settings(import_project):
    project, provider, _ = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    result = TimelinePipeline(service.workspace).prepare_timeline_import(
        service, FIXTURE, actor="fixture-editor", reason="Inspect without assumptions"
    )
    assert result["status"] == "blocked"
    assert result["readiness"]["activationAllowed"] is False
    session = service.load(result["importId"])
    assert session["options"] == {
        "mediaRoots": [],
        "mappings": {},
        "declarations": {},
    }
    assert (
        service.read_ref(result["importId"], session["refs"]["export"])
        == FIXTURE.read_bytes()
    )
    assert not service.workspace.artifact_path("cmap").exists()
    assert not service.workspace.pipeline_run_path.exists()
