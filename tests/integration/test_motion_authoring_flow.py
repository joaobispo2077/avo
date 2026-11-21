"""Canonical publication uses real owner preflight and bounded recovery."""

from copy import deepcopy

import pytest
from tests.test_motion_authoring import heads, item, propose, request, select
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_bmap_service import approved_workspace, cue
from tests.test_timeline_tracks_service import canonical_tracks

from avo.timeline.animation import AnimationService
from avo.timeline.bmap_service import BMapService
from avo.timeline.motion_authoring import MotionAuthoringError, MotionAuthoringService
from avo.timeline.store import StoreError, motion_application_access, timeline_writer
from avo.timeline.tracks import TracksService


def prepared_request(workspace):
    proposed, _ = propose(workspace)
    selected = select(workspace, proposed)
    return request(
        workspace,
        "plan-apply",
        "apply-first",
        selection={
            "proposalHash": proposed["proposalRef"]["sha256"],
            "decisionHash": selected["decisionRef"]["sha256"],
        },
        authoring={
            "bmap": {"cues": [cue()]},
            "tracks": canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
            "animation": strategy(),
        },
    )


def test_owner_preparation_is_pure_and_predicts_exact_published_revision(tmp_path):
    workspace, _, _ = approved_workspace(tmp_path)
    owner = BMapService(workspace)
    before = heads(workspace)
    with timeline_writer(workspace.timeline_dir):
        prepared = owner.prepare_authoring(
            {"cues": [cue()]}, actor="creator", reason="Exact preparation"
        )
        assert heads(workspace) == before
        actual = owner.author(
            {"cues": [cue()]},
            actor="creator",
            reason="Exact preparation",
            prepared=prepared,
        )
    assert actual["contentHash"] == prepared["contentSha256"]
    assert actual["revisionId"] == prepared["revisionId"]


@pytest.mark.parametrize("field", ["snapshot", "actor", "basis", "head"])
def test_prepared_body_cannot_change_validated_owner_intent(tmp_path, field):
    workspace, _, _ = approved_workspace(tmp_path)
    owner = BMapService(workspace)
    prepared = owner.prepare_authoring(
        {"cues": [cue()]}, actor="creator", reason="Exact preparation"
    )
    if field == "snapshot":
        prepared["snapshot"]["cues"][0]["intent"] = "Different intent"
    elif field == "actor":
        prepared["actor"]["id"] = "someone-else"
    elif field == "basis":
        prepared["basis"][0]["contentSha256"] = "0" * 64
    else:
        owner.author({"cues": [cue()]}, actor="creator", reason="Intervening revision")
    before = heads(workspace)
    with pytest.raises((ValueError, RuntimeError)):
        owner.author(
            {"cues": [cue()]},
            actor="creator",
            reason="Exact preparation",
            prepared=prepared,
        )
    assert heads(workspace) == before


def test_all_artifacts_publish_from_exact_approved_cut(tmp_path):
    workspace, _, cut_hash = approved_workspace(tmp_path)
    value = prepared_request(workspace)
    result = MotionAuthoringService(workspace).apply(value)
    assert result["status"] == "committed"
    assert set(result["committedHeads"]) == {"bmap", "tracks", "animation"}
    shown = MotionAuthoringService(workspace).show()
    assert shown["status"] == "selected"
    assert shown["applied"] is True
    assert BMapService(workspace).status()["basis"]["outputSha256"] == cut_hash
    assert (
        MotionAuthoringService(workspace).apply(value)["committedHeads"]
        == result["committedHeads"]
    )
    assert all(
        len(workspace.store(name).load_index()["revisionRefs"]) == 1
        for name in result["committedHeads"]
    )


@pytest.mark.parametrize("invalid", ["source", "timing", "component"])
def test_every_payload_is_prevalidated_before_first_canonical_write(tmp_path, invalid):
    workspace, _, _ = approved_workspace(tmp_path)
    value = prepared_request(workspace)
    if invalid == "source":
        value["authoring"]["tracks"]["videoTracks"]["layers"][0]["source"]["sha256"] = (
            "0" * 64
        )
    elif invalid == "timing":
        value["authoring"]["animation"]["components"][0]["startTicks"] = 10
    else:
        value["authoring"]["animation"]["components"][0]["lifecycle"].pop("hold")
    before = heads(workspace)
    with pytest.raises(MotionAuthoringError):
        MotionAuthoringService(workspace).apply(value)
    assert heads(workspace) == before


def test_bmap_only_apply_does_not_invent_resolved_downstream_artifacts(tmp_path):
    workspace, _, _ = approved_workspace(tmp_path)
    value = prepared_request(workspace)
    value["authoring"] = {"bmap": value["authoring"]["bmap"]}
    result = MotionAuthoringService(workspace).apply(value)
    assert set(result["committedHeads"]) == {"bmap"}
    assert workspace.store("tracks").load_index()["headRevisionId"] is None
    assert workspace.store("animation").load_index()["headRevisionId"] is None


@pytest.mark.parametrize("after_commit", [False, True])
def test_interrupted_publication_is_guarded_and_resumes_exactly_once(
    tmp_path, monkeypatch, after_commit
):
    workspace, _, _ = approved_workspace(tmp_path)
    value = prepared_request(workspace)
    original = TracksService.author

    def interrupted(owner, *args, **kwargs):
        if after_commit:
            original(owner, *args, **kwargs)
        raise OSError("Simulated interruption")

    with monkeypatch.context() as patch:
        patch.setattr(TracksService, "author", interrupted)
        with pytest.raises(MotionAuthoringError) as error:
            MotionAuthoringService(workspace).apply(value)
        assert error.value.code == "MOTION_RECOVERY_REQUIRED"
    with pytest.raises(StoreError, match="RECOVERY_REQUIRED"):
        BMapService(workspace).author(
            {"cues": [cue()]}, actor="creator", reason="Unrelated mutation"
        )
    result = MotionAuthoringService(workspace).apply(value)
    assert result["status"] == "committed"
    assert all(
        len(workspace.store(name).load_index()["revisionRefs"]) == 1
        for name in ("bmap", "tracks", "animation")
    )
    assert not (workspace.timeline_dir / "motion-application.pending.json").exists()


def test_unapproved_cut_does_not_become_timing_authority(footage_project_factory):
    workspace = footage_project_factory()
    proposed, _ = propose(workspace)
    selected = select(workspace, proposed)
    value = request(
        workspace,
        "plan-apply",
        "unapproved-apply",
        selection={
            "proposalHash": proposed["proposalRef"]["sha256"],
            "decisionHash": selected["decisionRef"]["sha256"],
        },
        authoring={"bmap": {"cues": [cue()]}},
    )
    before = heads(workspace)
    with pytest.raises(MotionAuthoringError):
        MotionAuthoringService(workspace).apply(value)
    assert heads(workspace) == before


def test_pending_motion_access_is_exact_writer_scoped_and_revoked(tmp_path):
    import json

    workspace, _, _ = approved_workspace(tmp_path)
    marker = {"operationId": "interrupted-apply", "requestHash": "a" * 64}
    (workspace.timeline_dir / "motion-application.pending.json").write_text(
        json.dumps(marker)
    )
    with pytest.raises(StoreError):
        with motion_application_access(workspace.timeline_dir, marker):
            pass
    with timeline_writer(workspace.timeline_dir, recovery=True):
        with motion_application_access(
            workspace.timeline_dir, {**marker, "requestHash": "b" * 64}
        ):
            with pytest.raises(StoreError, match="RECOVERY_REQUIRED"):
                workspace.require_active("cmap")
        with motion_application_access(workspace.timeline_dir, marker):
            assert workspace.require_active("cmap")["headRevisionId"]
    with pytest.raises(StoreError, match="RECOVERY_REQUIRED"):
        workspace.require_active("cmap")


def test_committed_receipt_cannot_invent_unpublished_canonical_revisions(tmp_path):
    workspace, _, _ = approved_workspace(tmp_path)
    value = prepared_request(workspace)
    service = MotionAuthoringService(workspace)
    with timeline_writer(workspace.timeline_dir):
        receipt = service._prepare(value, service.show())
        receipt["state"] = "committed"
        receipt["committedHeads"] = {
            name: {"revisionId": body["revisionId"], "sha256": body["contentSha256"]}
            for name, body in receipt["prepared"].items()
        }
        service._save_receipt(value, receipt)
    before = heads(workspace)
    with pytest.raises(MotionAuthoringError):
        service.apply(value)
    assert heads(workspace) == before


def test_partial_selection_cannot_change_unselected_global_motion_settings(tmp_path):
    workspace, _, _ = approved_workspace(tmp_path)
    BMapService(workspace).author(
        {"cues": [cue()]}, actor="creator", reason="Existing beat"
    )
    TracksService(workspace).author(
        canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
        actor="creator",
        reason="Existing tracks",
    )
    original = strategy()
    original["components"].append(
        {**deepcopy(original["components"][0]), "componentId": "creator-note"}
    )
    AnimationService(workspace).author(
        original, actor="creator", reason="Preserve another creator choice"
    )
    value = prepared_request(workspace)
    changed = deepcopy(original)
    changed["density"] = 5
    value["authoring"] = {"animation": changed}
    before = heads(workspace)
    with pytest.raises(MotionAuthoringError, match="Unselected"):
        MotionAuthoringService(workspace).apply(value)
    assert heads(workspace) == before


def test_committed_receipt_cannot_reuse_other_request_revisions(tmp_path):
    workspace, _, _ = approved_workspace(tmp_path)
    value = prepared_request(workspace)
    service = MotionAuthoringService(workspace)
    previous = service.apply(value)
    from avo.editing_craft import resolve_editing_craft_selection

    proposed = service.propose(
        request(
            workspace,
            "plan-propose",
            "unrelated-concept",
            selection=resolve_editing_craft_selection(),
            proposal={"items": [{**item(), "concept": "Different selected direction"}]},
        )
    )
    selected = service.select(
        request(
            workspace,
            "plan-select",
            "unrelated-selection",
            selection={
                "proposalHash": proposed["proposalRef"]["sha256"],
                "dispositions": [
                    {
                        "itemId": "mo04",
                        "status": "selected",
                        "reason": "Select revision",
                    }
                ],
            },
        )
    )
    changed = request(
        workspace,
        "plan-apply",
        "unrelated-application",
        selection={
            "proposalHash": proposed["proposalRef"]["sha256"],
            "decisionHash": selected["decisionRef"]["sha256"],
        },
        authoring=value["authoring"],
    )
    with timeline_writer(workspace.timeline_dir):
        receipt = service._prepare(changed, service.show())
        receipt["prepared"] = previous["receipt"]["prepared"]
        receipt["committedHeads"] = previous["receipt"]["committedHeads"]
        receipt["state"] = "committed"
        service._save_receipt(changed, receipt)
    before = heads(workspace)
    with pytest.raises(MotionAuthoringError):
        service.apply(changed)
    assert heads(workspace) == before


def test_profile_command_cannot_use_motion_plan_to_mutate_parent(tmp_path):
    from avo.timeline.command_handlers import CommandHandlers
    from avo.timeline.command_registry import CommandPermissionError
    from avo.timeline.pipeline import TimelinePipeline

    workspace, _, _ = approved_workspace(tmp_path)
    handlers = CommandHandlers(TimelinePipeline(workspace))
    before = heads(workspace)
    with pytest.raises(CommandPermissionError):
        handlers.execute("talking-head", "plan-apply", {"mutation": "bmap"})
    with pytest.raises(ValueError, match="cannot mutate parent"):
        handlers.execute(
            "talking-head",
            "plan-apply",
            {
                "targetScope": "child",
                "parentTimelineRef": "parent:cmap-r0001:sha256",
                "childProject": str(workspace.project_path),
            },
        )
    assert heads(workspace) == before
