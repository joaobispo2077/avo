"""Selected chunks publish once and retain exact per-item work across restarts."""

from copy import deepcopy

import pytest
from tests.integration.test_camera_authoring_flow import (
    camera_application,
)
from tests.integration.test_editing_craft_resume import fresh_map
from tests.test_camera_commands import declared_camera as camera_capability_fixture
from tests.test_motion_authoring import item, request
from tests.test_timeline_bmap_service import approved_workspace, cue

from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.motion_authoring import MotionAuthoringError, MotionAuthoringService

declared_camera = pytest.fixture(name="declared_camera")(
    camera_capability_fixture.__wrapped__
)


def selected_world(tmp_path):
    workspace, _, _ = approved_workspace(tmp_path)
    service = MotionAuthoringService(workspace)
    second = item("mo05")
    second["cueId"] = "cue-two"
    proposed = service.propose(
        request(
            workspace,
            "plan-propose",
            "scoped-concepts",
            selection=resolve_editing_craft_selection(),
            proposal={"items": [item(), second]},
        )
    )
    selected = service.select(
        request(
            workspace,
            "plan-select",
            "scoped-select",
            selection={
                "proposalHash": proposed["proposalRef"]["sha256"],
                "dispositions": [
                    {
                        "itemId": identity,
                        "status": "selected",
                        "reason": "Produce this item in its own section",
                    }
                    for identity in ("mo04", "mo05")
                ],
            },
        )
    )
    first, later = cue(), cue()
    first["contentRef"]["itemId"] = "mo04"
    later["cueId"] = "cue-two"
    later["contentRef"]["itemId"] = "mo05"
    later["start"]["ticks"], later["end"]["ticks"] = 600, 900
    return workspace, service, proposed, selected, first, later


def apply_chunk(workspace, proposed, selected, identity, chunks, cues):
    return request(
        workspace,
        "plan-apply",
        identity,
        selection={
            "proposalHash": proposed["proposalRef"]["sha256"],
            "decisionHash": selected["decisionRef"]["sha256"],
        },
        productionScope={
            "clock": {"frameRate": {"num": 24, "den": 1}, "programEndFrame": 24},
            "chunks": [
                {"chunkId": "opening", "startFrame": 0, "endFrameExclusive": 12},
                {"chunkId": "ending", "startFrame": 12, "endFrameExclusive": 24},
            ],
            "selectedChunkIds": chunks,
        },
        authoring={"bmap": {"cues": deepcopy(cues)}},
    )


def test_each_chunk_publishes_only_its_items_and_keeps_other_work_pending(tmp_path):
    workspace, service, proposed, selected, first, later = selected_world(tmp_path)
    opening = apply_chunk(
        workspace, proposed, selected, "produce-opening", ["opening"], [first]
    )
    result = service.apply(opening)
    assert result["receipt"]["appliedItemIds"] == ["mo04"]
    shown = MotionAuthoringService(workspace).show()
    assert shown["applied"] is False
    assert shown["appliedItemIds"] == ["mo04"]
    snapshot = fresh_map(workspace)
    work = next(
        row
        for row in snapshot["pendingRevisions"]
        if row["operationId"] == "scoped-concepts"
    )
    assert work["status"] == "partial"
    assert work["completedIds"] == ["mo04"] and work["pendingIds"] == ["mo05"]
    dispositions = {row["itemId"]: row["disposition"] for row in snapshot["items"]}
    assert dispositions == {"mo04": "applied", "mo05": "selected"}
    ending = apply_chunk(
        workspace, proposed, selected, "produce-ending", ["ending"], [first, later]
    )
    result = MotionAuthoringService(workspace).apply(ending)
    assert result["receipt"]["appliedItemIds"] == ["mo05"]
    shown = MotionAuthoringService(workspace).show()
    assert shown["applied"] is True
    assert shown["appliedItemIds"] == ["mo04", "mo05"]
    before = workspace.pipeline_run_path.read_bytes()
    revisions = workspace.store("bmap").load_index()["revisionRefs"]
    service.apply(opening)
    assert workspace.pipeline_run_path.read_bytes() == before
    assert workspace.store("bmap").load_index()["revisionRefs"] == revisions
    work = next(
        row
        for row in fresh_map(workspace)["pendingRevisions"]
        if row["operationId"] == "scoped-concepts"
    )
    assert work["status"] == "completed" and work["pendingIds"] == []
    from avo.timeline.lifecycle import PipelineRunStore
    from avo.timeline.motion_retention import retained_motion_paths

    kept = set(retained_motion_paths(workspace))
    history = PipelineRunStore(workspace.pipeline_run_path).load()["extensions"][
        "motionApplicationHistory"
    ]
    assert len(history) == 2
    assert all(
        workspace.raw_dir / entry["receiptRef"]["path"] in kept for entry in history
    )


@pytest.mark.parametrize("problem", ["context-only", "foreign-cue"])
def test_selected_chunk_cannot_publish_context_or_outside_contributions(
    tmp_path, problem
):
    workspace, service, proposed, selected, first, later = selected_world(tmp_path)
    chunks = ["ending"] if problem == "context-only" else ["opening"]
    cues = [first] if problem == "context-only" else [first, later]
    value = apply_chunk(workspace, proposed, selected, "invalid-chunk", chunks, cues)
    before = workspace.store("bmap").load_index()
    with pytest.raises(MotionAuthoringError):
        service.apply(value)
    assert workspace.store("bmap").load_index() == before
    assert not service._pending.exists()


def test_split_item_publishes_all_its_parts_once_in_its_start_chunk(tmp_path):
    workspace, service, proposed, selected, first, later = selected_world(tmp_path)
    continuation = deepcopy(later)
    continuation["cueId"] = "cue-continuation"
    continuation["contentRef"]["itemId"] = "mo04"
    value = apply_chunk(
        workspace,
        proposed,
        selected,
        "produce-split",
        ["opening"],
        [first, continuation],
    )
    result = service.apply(value)
    plan = result["receipt"]["productionScope"]
    assert result["receipt"]["appliedItemIds"] == ["mo04"]
    assert [row["itemId"] for row in plan["production"]] == ["mo04"]
    assert plan["production"][0]["consumerChunkIds"] == ["opening"]
    assert [part["cueId"] for part in plan["production"][0]["parts"]] == [
        "cue-one",
        "cue-continuation",
    ]
    assert result["reviewReady"] is True


def test_scoped_publication_cannot_create_shared_picture_or_dialogue_layers(tmp_path):
    from tests.test_timeline_tracks_service import canonical_tracks

    workspace, service, proposed, selected, first, _ = selected_world(tmp_path)
    value = apply_chunk(
        workspace, proposed, selected, "shared-layer", ["opening"], [first]
    )
    value["authoring"]["tracks"] = canonical_tracks(
        workspace, workspace.raw_dir / "raw.bin"
    )
    before = {name: workspace.store(name).load_index() for name in ("bmap", "tracks")}
    with pytest.raises(MotionAuthoringError, match="Unselected|scope"):
        service.apply(value)
    assert {name: workspace.store(name).load_index() for name in before} == before


def test_receipt_resealing_cannot_turn_partial_publication_into_other_item_completion(
    tmp_path,
):
    from avo.timeline.store import atomic_write_json

    workspace, service, proposed, selected, first, _ = selected_world(tmp_path)
    value = apply_chunk(
        workspace, proposed, selected, "partial-receipt", ["opening"], [first]
    )
    result = service.apply(value)
    forged = deepcopy(result["receipt"])
    forged["appliedItemIds"] = ["mo05"]
    reference = service._put("receipts", forged, "receipt")
    atomic_write_json(service._application_path(value), reference)
    before = workspace.store("bmap").load_index()
    with pytest.raises(ValueError, match="ownership"):
        service.apply(value)
    assert workspace.store("bmap").load_index() == before


def test_application_history_rejects_aliases_duplicates_and_detached_requests(tmp_path):
    from avo.timeline.lifecycle import PipelineRunStore
    from avo.timeline.store import atomic_write_json

    workspace, service, proposed, selected, first, _ = selected_world(tmp_path)
    service.apply(
        apply_chunk(
            workspace, proposed, selected, "history-first", ["opening"], [first]
        )
    )
    store = PipelineRunStore(workspace.pipeline_run_path)
    original = store.load()
    for problem in ("alias", "duplicate", "detached"):
        changed = deepcopy(original)
        entries = changed["extensions"]["motionApplicationHistory"]
        if problem == "alias":
            entries[0]["receiptRef"]["path"] = "edit/motion/receipts/../wrong.json"
        elif problem == "duplicate":
            entries.append(deepcopy(entries[0]))
        else:
            entries[0]["requestId"] = "unrecorded-request"
        atomic_write_json(store.path, changed)
        with pytest.raises((ValueError, RuntimeError)):
            store.load()
    atomic_write_json(store.path, original)
    assert MotionAuthoringService(workspace).show()["appliedItemIds"] == ["mo04"]


@pytest.mark.parametrize("explicit_identity", [True, False])
def test_retiming_cannot_steal_an_existing_item_from_an_unselected_start_chunk(
    tmp_path,
    explicit_identity,
):
    workspace, service, proposed, selected, first, _ = selected_world(tmp_path)
    initial = apply_chunk(
        workspace, proposed, selected, "owner-first", ["opening"], [first]
    )
    if not explicit_identity:
        initial["authoring"]["bmap"]["cues"][0]["contentRef"].pop("itemId")
        initial.pop("productionScope")
    service.apply(initial)
    moved = deepcopy(first)
    moved["start"]["ticks"], moved["end"]["ticks"] = 600, 900
    before = workspace.store("bmap").load_index()
    invalid = apply_chunk(
        workspace, proposed, selected, "steal-owner", ["ending"], [moved]
    )
    with pytest.raises(MotionAuthoringError, match="canonical start"):
        service.apply(invalid)
    assert workspace.store("bmap").load_index() == before
    allowed = apply_chunk(
        workspace, proposed, selected, "move-owner", ["opening", "ending"], [moved]
    )
    assert service.apply(allowed)["receipt"]["appliedItemIds"] == ["mo04"]


def test_scoped_camera_keeps_independent_graphic_and_dialogue_unchanged(
    tmp_path, declared_camera
):
    workspace, service, value, original_animation, original_tracks = camera_application(
        tmp_path
    )
    value["productionScope"] = {
        "clock": {"frameRate": {"num": 24, "den": 1}, "programEndFrame": 24},
        "chunks": [
            {"chunkId": "opening", "startFrame": 0, "endFrameExclusive": 12},
            {"chunkId": "ending", "startFrame": 12, "endFrameExclusive": 24},
        ],
        "selectedChunkIds": ["opening"],
    }
    result = service.apply(value)
    assert result["receipt"]["appliedItemIds"] == ["mo04"]
    animation = workspace.store("animation").load()["revisions"][-1]["snapshot"]
    assert animation["components"][0] == original_animation["snapshot"]["components"][0]
    tracks = workspace.store("tracks").load()["revisions"][-1]["snapshot"]
    assert tracks["audioTracks"] == original_tracks["snapshot"]["audioTracks"]


def test_scoped_revision_cannot_clear_an_unresolved_parent_state(tmp_path):
    from avo.timeline.store import atomic_write_json

    workspace, service, proposed, selected, first, _ = selected_world(tmp_path)
    service.apply(
        apply_chunk(workspace, proposed, selected, "parent-first", ["opening"], [first])
    )
    store = workspace.store("bmap")
    stale = store.load_index()
    stale["activeState"] = "stale"
    atomic_write_json(store.path, stale)
    value = apply_chunk(
        workspace, proposed, selected, "parent-revision", ["opening"], [first]
    )
    with pytest.raises(MotionAuthoringError, match="valid BMap"):
        service.apply(value)
    assert store.load_index() == stale


def test_application_history_budget_fails_before_first_canonical_write(tmp_path):
    import hashlib

    from avo.timeline.lifecycle import PipelineRunStore
    from avo.timeline.store import atomic_write_json

    workspace, service, proposed, selected, first, _ = selected_world(tmp_path)
    store = PipelineRunStore(workspace.pipeline_run_path)
    run = store.load()
    history = []
    for ordinal in range(500):
        digest = hashlib.sha256(str(ordinal).encode()).hexdigest()
        entry = deepcopy(run["extensions"]["motionProposalSelection"])
        entry["proposalRef"] = {
            "path": f"edit/motion/proposals/{digest}.json",
            "sha256": digest,
        }
        entry["receiptRef"] = {
            "path": f"edit/motion/receipts/{digest}.json",
            "sha256": digest,
        }
        history.append(entry)
    run["extensions"]["motionApplicationHistory"] = history
    atomic_write_json(store.path, run)
    # These unrelated references are structurally valid metadata, not claimed
    # qualified applications; the capacity guard must run before publishing.
    assert len(store.load()["extensions"]["motionApplicationHistory"]) == 500
    value = apply_chunk(
        workspace, proposed, selected, "over-budget", ["opening"], [first]
    )
    before = workspace.store("bmap").load_index()
    with pytest.raises(MotionAuthoringError, match="500-record budget"):
        service.apply(value)
    assert workspace.store("bmap").load_index() == before
    assert not service._pending.exists()
