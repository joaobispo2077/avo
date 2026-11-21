"""Fresh processes recover requested work from bounded metadata, without media work."""

import json
import subprocess
import sys
from copy import deepcopy

import pytest
from tests.test_motion_authoring import propose
from tests.test_motion_authoring import request as motion_request
from tests.test_sfx_catalog import annotate
from tests.test_sound_application import application
from tests.test_sound_proposals import prepared

from avo.timeline.motion_authoring import MotionAuthoringService
from avo.timeline.motion_retention import retained_motion_paths
from avo.timeline.sound_planning import SoundPlanningService
from avo.timeline.workspace import TimelineWorkspace


def fresh_map(workspace):
    script = """
import json, sys
from pathlib import Path
from avo.timeline import contracts
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.workspace import TimelineWorkspace
def forbidden(*args, **kwargs):
    raise AssertionError('Default pending inspection accessed source media')
contracts.file_fingerprint = forbidden
print(json.dumps(TimelinePipeline(TimelineWorkspace.from_project(Path(sys.argv[1]), video_id=sys.argv[2])).motion_plan()))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-c",
            script,
            str(workspace.project_path),
            workspace.video_id,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def test_pending_sound_requests_keep_exact_original_scope_in_a_fresh_process(tmp_path):
    workspace, catalogue, request = prepared(tmp_path)
    service = SoundPlanningService(workspace, catalogue=catalogue)
    first = service.propose(request)
    second_request = deepcopy(request)
    second_request["operationId"] = "sound-second-pending"
    second_request["intents"][0]["eventId"] = "sound-second-event"
    second = service.propose(second_request)
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    snapshot = fresh_map(workspace)
    pending = {row["operationId"]: row for row in snapshot["pendingRevisions"]}
    assert set(pending) == {request["operationId"], second_request["operationId"]}
    for source, supplied in ((first, request), (second, second_request)):
        row = pending[supplied["operationId"]]
        assert row["kind"] == "sound"
        assert row["status"] == "awaiting-selection"
        assert row["basisStatus"] == "current"
        assert row["proposalRef"] == source["proposalRef"]
        assert row["itemIds"] == ["mo04"]
        assert row["pendingIds"] == [supplied["intents"][0]["eventId"]]
        assert row["completedIds"] == []
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before
    generation = catalogue.show()
    annotate(
        catalogue,
        generation["generationId"],
        generation["entries"][0]["entryId"],
        {"curation": {"favorite": True}},
    )
    changed = fresh_map(workspace)["pendingRevisions"]
    assert all(row["basisStatus"] == "stale" for row in changed)
    assert {row["operationId"] for row in changed} == set(pending)
    (workspace.raw_dir / second["proposalRef"]["path"]).write_bytes(b"damaged metadata")
    damaged_before = {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    }
    damaged = {
        row["operationId"]: row for row in fresh_map(workspace)["pendingRevisions"]
    }
    unavailable = damaged[second_request["operationId"]]
    assert unavailable["status"] == unavailable["basisStatus"] == "unavailable"
    assert unavailable["itemIds"] == ["mo04"]
    assert unavailable["pendingIds"] == ["sound-second-event"]
    assert damaged[request["operationId"]]["status"] == "awaiting-selection"
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == damaged_before


def test_unapplied_motion_requests_and_predecessors_survive_restart_and_retention(
    tmp_path,
):
    path = tmp_path / "avo.project.json"
    path.write_text(
        json.dumps(
            {"provider": "example", "videoId": "pending", "rawDir": str(tmp_path)}
        )
    )
    workspace = TimelineWorkspace.from_project(path)
    first, _ = propose(workspace)
    second = MotionAuthoringService(workspace).propose(
        motion_request(
            workspace,
            "plan-propose",
            "concept-second",
            selection=first["proposal"]["options"],
            proposal={
                "items": first["proposal"]["items"],
                "predecessor": first["proposalRef"]["sha256"],
            },
        )
    )
    assert second["proposalRef"] != first["proposalRef"]
    pending = fresh_map(workspace)["pendingRevisions"]
    assert len(pending) == 2
    assert all(row["status"] == "awaiting-selection" for row in pending)
    assert all(row["itemIds"] == row["pendingIds"] == ["mo04"] for row in pending)
    retained = retained_motion_paths(workspace)
    assert all(
        workspace.raw_dir / shown["proposalRef"]["path"] in retained
        for shown in (first, second)
    )


def test_empty_sound_request_leaves_no_effect_or_selection_pending(
    tmp_path, monkeypatch
):
    from avo.timeline.motion_review import MotionReviewService

    workspace, catalogue, request = prepared(tmp_path)
    original = MotionReviewService(workspace).project()["basisHeads"]
    request["intents"] = []

    def forbidden(*args, **kwargs):
        raise AssertionError("An empty sound request searched for effects")

    monkeypatch.setattr(catalogue, "search", forbidden)
    SoundPlanningService(workspace, catalogue=catalogue).propose(request)
    snapshot = fresh_map(workspace)
    row = snapshot["pendingRevisions"][0]
    assert row["status"] == "completed"
    assert row["pendingIds"] == row["completedIds"] == []
    assert snapshot["basisHeads"] == original


@pytest.mark.parametrize("interrupted", [False, True])
def test_restart_distinguishes_pending_recovery_from_actual_completed_sound(
    tmp_path, monkeypatch, interrupted
):
    from avo.timeline.sound_planning import SoundPlanningError
    from avo.timeline.tracks import TracksService

    workspace, _, service, probe, request, shown = application(tmp_path)
    if interrupted:
        author = TracksService.author

        def fail(*args, **kwargs):
            raise OSError("fixture interrupted Tracks publication")

        monkeypatch.setattr(TracksService, "author", fail)
        with pytest.raises(SoundPlanningError, match="recovery"):
            service.apply(request)
        pending = fresh_map(workspace)["pendingRevisions"][0]
        assert pending["status"] == "recovery-needed"
        assert pending["completedIds"] == []
        assert pending["pendingIds"] == [request["choices"][0]["eventId"]]
        assert set(pending["applications"][0]["committedHeads"]) == {"bmap"}
        monkeypatch.setattr(TracksService, "author", author)
    service.apply(request)
    calls = len(probe.calls)
    pending = fresh_map(workspace)["pendingRevisions"][0]
    assert pending["status"] == "completed"
    assert pending["pendingIds"] == []
    assert pending["completedIds"] == [request["choices"][0]["eventId"]]
    assert len(probe.calls) == calls
    assert workspace.raw_dir / shown["proposalRef"]["path"] in retained_motion_paths(
        workspace
    )


def unchanged_fresh_map(workspace):
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    snapshot = fresh_map(workspace)
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before
    return snapshot


def partial_motion(tmp_path):
    from tests.integration.test_craft_scope_publication import (
        apply_chunk,
        selected_world,
    )

    workspace, service, proposed, selected, first, _ = selected_world(tmp_path)
    service.apply(
        apply_chunk(
            workspace, proposed, selected, "restart-opening", ["opening"], [first]
        )
    )
    return workspace, proposed


def motion_work(snapshot, identity="scoped-concepts"):
    return next(
        row for row in snapshot["pendingRevisions"] if row["operationId"] == identity
    )


@pytest.mark.parametrize("changed", ["source", "asset"])
def test_changed_canonical_dependency_retains_exact_partial_work_after_restart(
    tmp_path, changed
):
    from tests.test_timeline_cmap_service import snapshot as cut_snapshot

    from avo.timeline.bmap_service import BMapService
    from avo.timeline.cmap_service import CMapService
    from avo.timeline.contracts import file_fingerprint

    workspace, proposed = partial_motion(tmp_path)
    if changed == "source":
        source = workspace.raw_dir / "raw.bin"
        source.write_bytes(b"changed synthetic source")
        CMapService(workspace).author(
            cut_snapshot(source), actor="fixture", reason="Changed source identity"
        )
    else:
        source = workspace.raw_dir / "changed-asset.bin"
        source.write_bytes(b"different synthetic asset")
        bmap = deepcopy(workspace.store("bmap").load()["revisions"][-1]["snapshot"])
        bmap["cues"][0]["assetRef"] = {
            "locator": str(source),
            **file_fingerprint(source),
        }
        BMapService(workspace).author(
            bmap, actor="fixture", reason="Changed asset identity"
        )
    snapshot = unchanged_fresh_map(workspace)
    work = motion_work(snapshot)
    assert work["status"] == "partial" and work["basisStatus"] == "stale"
    assert work["scope"]["itemIds"] == ["mo04", "mo05"]
    assert work["completedIds"] == ["mo04"] and work["pendingIds"] == ["mo05"]
    assert work["proposalRef"] == proposed["proposalRef"]
    assert snapshot["readiness"] == "stale"


def test_future_preferences_do_not_retarget_frozen_partial_work_after_restart(tmp_path):
    workspace, proposed = partial_motion(tmp_path)
    project = json.loads(workspace.project_path.read_text(encoding="utf-8"))
    project["editingCraft"] = {"soundMatching": {"enabled": True}}
    workspace.project_path.write_text(json.dumps(project), encoding="utf-8")
    snapshot = unchanged_fresh_map(workspace)
    work = motion_work(snapshot)
    assert work["status"] == "partial" and work["basisStatus"] == "current"
    assert snapshot["options"] == proposed["proposal"]["options"]
    assert snapshot["options"]["effective"]["soundMatching"]["enabled"] is False
    assert work["completedIds"] == ["mo04"] and work["pendingIds"] == ["mo05"]


def test_changed_direction_keeps_the_original_pending_request_after_restart(tmp_path):
    from tests.test_briefstart_context import selected_project
    from tests.test_motion_authoring import select

    project, brief, reference, _ = selected_project(tmp_path)
    workspace = TimelineWorkspace.from_project(project)
    proposed, _ = propose(workspace)
    select(workspace, proposed)
    brief.decide(
        {
            "requestId": "restart-select-compare",
            "targetRef": reference,
            "expectedIndexHash": brief.show()["expectedIndexHash"],
            "action": "select",
            "scope": "project",
            "actor": {"type": "human", "id": "fixture-creator"},
            "reason": "Changed fixture direction",
            "humanInstruction": {
                "source": "session:fixture",
                "text": "Select compare for this synthetic test.",
            },
            "optionId": "compare",
        }
    )
    snapshot = unchanged_fresh_map(workspace)
    work = motion_work(snapshot, proposed["proposal"]["operationId"])
    assert work["basisStatus"] == "stale"
    assert work["pendingIds"] == ["mo04"] and work["completedIds"] == []
    assert work["proposalRef"] == proposed["proposalRef"]
    assert (
        MotionAuthoringService(workspace).show()["proposal"]["direction"]["optionId"]
        == "quiet"
    )


def test_changed_camera_keeps_historical_completion_separate_from_currentness(tmp_path):
    from tests.integration.test_camera_authoring_flow import camera_application

    from avo.timeline.animation import AnimationService

    workspace, service, request, _, _ = camera_application(tmp_path)
    applied = service.apply(request)
    animation = deepcopy(
        workspace.store("animation").load()["revisions"][-1]["snapshot"]
    )
    camera = next(
        c
        for c in animation["components"]
        if "editingCraft" in (c.get("extensions") or {})
    )
    camera["extensions"]["editingCraft"]["camera"]["nodes"][-1]["scale"] += 0.01
    AnimationService(workspace).author(
        animation, actor="fixture", reason="Changed camera path"
    )
    snapshot = unchanged_fresh_map(workspace)
    work = next(row for row in snapshot["pendingRevisions"] if row["kind"] == "motion")
    assert work["status"] == "completed" and work["basisStatus"] == "stale"
    assert (
        work["pendingIds"] == [] and work["completedIds"] == applied["appliedItemIds"]
    )
    assert snapshot["readiness"] == "stale"


def test_changed_sound_catalogue_keeps_original_completion_and_pending_listening(
    tmp_path,
):
    workspace, catalogue, service, _, request, _ = application(tmp_path)
    applied = service.apply(request)
    generation = catalogue.show()
    annotate(
        catalogue,
        generation["generationId"],
        generation["entries"][0]["entryId"],
        {"curation": {"favorite": True}},
    )
    work = unchanged_fresh_map(workspace)["pendingRevisions"][0]
    assert work["status"] == "completed" and work["basisStatus"] == "stale"
    assert work["completedIds"] == [request["choices"][0]["eventId"]]
    assert work["pendingIds"] == []
    assert applied["acceptance"] == "pending-listening"
