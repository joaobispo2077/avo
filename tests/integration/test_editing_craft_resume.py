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
