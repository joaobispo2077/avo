"""Reuse current canonical work; presentation and catalogue edits grant no approvals."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.sfx_catalog import SfxCatalogService
from avo.timeline.bmap_service import BMapService
from avo.timeline.contracts import document_hash_excluding
from avo.timeline.materialize import canonical_proof_media_inputs
from avo.timeline.motion_review import MotionReviewService
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.workspace import TimelineWorkspace, WorkspaceError
from tests.test_proof_plan import regression_contract
from tests.test_sfx_catalog import Facts, scan
from tests.test_sound_proof_plan import published_program


def canonical_state(workspace):
    paths = [p for p in workspace.timeline_dir.rglob("*") if p.is_file()]
    if workspace.pipeline_run_path.is_file():
        paths.append(workspace.pipeline_run_path)
    return {p: p.read_bytes() for p in paths}


def preflight(workspace, compiler, plan):
    return compiler.preflight(
        plan,
        media_inputs=canonical_proof_media_inputs(workspace, plan),
        tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
    )


def blank_workspace(directory):
    path = directory / "avo.project.json"
    path.write_text(
        json.dumps(
            {"provider": "example", "videoId": "review", "rawDir": str(directory)}
        ),
        encoding="utf-8",
    )
    return TimelineWorkspace.from_project(path)


def test_native_report_observes_changed_live_default_options(tmp_path):
    workspace = blank_workspace(tmp_path)
    snapshot = TimelinePipeline(workspace).motion_plan()
    review = MotionReviewService(workspace)
    review.publish(snapshot, expected_basis=snapshot["basisHeads"])
    assert review.report_status(snapshot)["freshness"] == "current"
    project = json.loads(workspace.project_path.read_text(encoding="utf-8"))
    project["editingCraft"] = {"camera": {"enabled": True}}
    workspace.project_path.write_text(json.dumps(project), encoding="utf-8")
    before = canonical_state(workspace)
    assert review.report_status(snapshot)["freshness"] == "historical"
    assert canonical_state(workspace) == before


def test_explicit_preview_observes_new_work_without_initializing_canonical_artifacts(
    tmp_path,
):
    from tests.test_motion_authoring import propose

    workspace = blank_workspace(tmp_path)
    review = MotionReviewService(workspace)
    snapshot = review.project()
    review.publish(snapshot, expected_basis=snapshot["basisHeads"])
    assert review.report_status(snapshot)["freshness"] == "current"
    propose(workspace)
    before = canonical_state(workspace)
    assert review.report_status(snapshot)["freshness"] == "historical"
    assert canonical_state(workspace) == before
    assert not workspace.artifact_path("cmap").is_file()


def test_frozen_current_view_survives_preference_changes_for_future_requests(tmp_path):
    from tests.integration.test_editing_craft_resume import partial_motion

    workspace, _ = partial_motion(tmp_path)
    review = MotionReviewService(workspace)
    snapshot = TimelinePipeline(workspace).motion_plan()
    review.publish(snapshot, expected_basis=snapshot["basisHeads"])
    project = json.loads(workspace.project_path.read_text(encoding="utf-8"))
    project["editingCraft"] = {"soundMatching": {"enabled": True}}
    workspace.project_path.write_text(json.dumps(project), encoding="utf-8")
    before = canonical_state(workspace)
    assert review.report_status(snapshot)["freshness"] == "current"
    assert canonical_state(workspace) == before


@pytest.mark.parametrize("version", ["1.8.0", "1.9.0"])
def test_older_report_remains_readable_without_claiming_current_context(tmp_path, version):
    workspace = blank_workspace(tmp_path)
    review = MotionReviewService(workspace)
    snapshot = review.project()
    if version == "1.8.0":
        snapshot.pop("contextBasis")
    snapshot["generator"]["version"] = version
    snapshot["snapshotHash"] = document_hash_excluding(snapshot, "snapshotHash")
    result = review.publish(snapshot, expected_basis=snapshot["basisHeads"])
    assert result["status"] == "stale"
    status = review.report_status(snapshot)
    assert status["freshness"] == "historical"
    assert Path(status["refs"]["snapshot"]).is_file()


def test_current_generator_requires_its_context_basis_before_publication(tmp_path):
    workspace = blank_workspace(tmp_path)
    review = MotionReviewService(workspace)
    snapshot = review.project()
    snapshot.pop("contextBasis")
    snapshot["snapshotHash"] = document_hash_excluding(snapshot, "snapshotHash")
    with pytest.raises(ValueError, match="contextBasis"):
        review.publish(snapshot, expected_basis=snapshot["basisHeads"])


def test_explicit_sound_context_is_reverified_without_media_execution(
    tmp_path, monkeypatch
):
    from tests.test_sound_application import application

    workspace, _, _, _, _, shown = application(tmp_path)
    snapshot = TimelinePipeline(workspace).motion_plan(
        sound_proposal={
            "proposal": shown["proposal"],
            "proposalRef": shown["proposalRef"],
        }
    )
    review = MotionReviewService(workspace)

    def forbidden(*args, **kwargs):
        pytest.fail("Report freshness started source analysis or model execution")

    monkeypatch.setattr("avo.timeline.contracts.file_fingerprint", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr(SfxCatalogService, "scan", forbidden)
    monkeypatch.setattr(SfxCatalogService, "search", forbidden)
    review.publish(snapshot, expected_basis=snapshot["basisHeads"])
    assert review.report_status(snapshot)["freshness"] == "current"
    (workspace.raw_dir / shown["proposalRef"]["path"]).write_text(
        "{}\n", encoding="utf-8"
    )
    before = canonical_state(workspace)
    status = review.report_status(snapshot)
    assert status["freshness"] == "historical"
    assert status["warnings"]
    assert Path(status["refs"]["snapshot"]).is_file()
    assert canonical_state(workspace) == before


def test_scope_report_regeneration_preserves_current_proof_and_canonical_state(
    tmp_path,
):
    workspace, compiler, request, _ = published_program(tmp_path)
    original = compiler.compile(request, regression_contract=regression_contract())
    assert preflight(workspace, compiler, original)["status"] == "pass"
    before = canonical_state(workspace)
    pipeline = TimelinePipeline(workspace)
    scope = {
        "clock": {"frameRate": {"num": 24, "den": 1}, "programEndFrame": 24},
        "chunks": [
            {"chunkId": "opening", "startFrame": 0, "endFrameExclusive": 12},
            {"chunkId": "ending", "startFrame": 12, "endFrameExclusive": 24},
        ],
        "selectedChunkIds": ["opening"],
    }
    first = pipeline.motion_plan(scope_request=scope)
    review = MotionReviewService(workspace)
    review.publish(first, expected_basis=first["basisHeads"])
    scope["selectedChunkIds"] = ["ending"]
    second = pipeline.motion_plan(scope_request=scope)
    review.publish(second, expected_basis=second["basisHeads"])
    assert first["snapshotHash"] != second["snapshotHash"]
    assert (
        first["productionScope"]["approval"]
        == second["productionScope"]["approval"]
        == "not-granted"
    )
    assert (
        review.report_status(first)["freshness"]
        == review.report_status(second)["freshness"]
        == "current"
    )
    assert canonical_state(workspace) == before
    assert (
        compiler.compile(request, regression_contract=regression_contract()) == original
    )
    assert preflight(workspace, compiler, original)["status"] == "pass"


def test_unrelated_catalogue_asset_reuses_current_work_but_changed_basis_stales_review(
    tmp_path,
):
    workspace, compiler, request, applied = published_program(tmp_path)
    plan = compiler.compile(request, regression_contract=regression_contract())
    assert preflight(workspace, compiler, plan)["status"] == "pass"
    pipeline, review = TimelinePipeline(workspace), MotionReviewService(workspace)
    snapshot = pipeline.motion_plan()
    review.publish(snapshot, expected_basis=snapshot["basisHeads"])
    before = canonical_state(workspace)
    catalogue = SfxCatalogService(workspace, roots={})
    original = catalogue.show()
    root = Path(original["roots"]["test"])
    (root / "unrelated.wav").write_bytes(b"unselected synthetic asset")
    catalogue = SfxCatalogService(workspace, roots=original["roots"], analyzer=Facts())
    current = scan(catalogue, original["generationId"])
    assert current["generationId"] != original["generationId"]
    selected = applied["receipt"]["choices"][0]["sourceEntry"]
    assert (
        next(e for e in current["entries"] if e["entryId"] == selected["entryId"])
        == selected
    )
    assert canonical_state(workspace) == before
    assert compiler.compile(request, regression_contract=regression_contract()) == plan
    assert preflight(workspace, compiler, plan)["status"] == "pass"
    assert review.report_status(snapshot)["freshness"] == "historical"
    refreshed = pipeline.motion_plan()
    review.publish(refreshed, expected_basis=refreshed["basisHeads"])
    assert review.report_status(refreshed)["freshness"] == "current"
    assert canonical_state(workspace) == before

    previous_tracks = deepcopy(
        workspace.store("tracks").load()["revisions"][-1]["snapshot"]
    )
    bmap = deepcopy(workspace.store("bmap").load()["revisions"][-1]["snapshot"])
    next(c for c in bmap["cues"] if c["kind"] == "text")["contentRef"]["text"] = (
        "Changed visual content"
    )
    BMapService(workspace).author(
        bmap, actor="fixture", reason="Relevant visual dependency changed"
    )
    assert (
        workspace.store("tracks").load()["revisions"][-1]["snapshot"] == previous_tracks
    )
    assert review.report_status(snapshot)["freshness"] == "historical"
    with pytest.raises(WorkspaceError, match="tracks is stale"):
        preflight(workspace, compiler, plan)
    assert applied["acceptance"] == "pending-listening"
