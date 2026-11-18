"""Sound revisions retain unchanged visual direction without composite approval."""

from copy import deepcopy

import pytest
from tests.integration.test_editing_craft_resume import fresh_map
from tests.test_motion_authoring import item, request, select
from tests.test_sound_application import application
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_tracks_service import canonical_tracks

from avo.timeline.motion_authoring import MotionAuthoringService
from avo.timeline.motion_review import MotionReviewService
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.workspace import WorkspaceError


def sound_proposal(workspace, service, original, operation_id):
    return service.propose(
        {
            "contractVersion": "1.0.0",
            "operation": "propose",
            "operationId": operation_id,
            "actor": "creator",
            "reason": "Revise the same requested sound event",
            "expectedBasis": TimelinePipeline(workspace).motion_plan()["basisHeads"],
            "selection": original["options"],
            "expectedGeneration": original["generationId"],
            "clock": original["clock"],
            "intents": [entry["intent"] for entry in original["opportunities"]],
        }
    )


def applied_motion_and_sound(tmp_path):
    workspace, _, audio_service, _, audio_request, original = application(tmp_path)
    motion = MotionAuthoringService(workspace)
    concept = motion.propose(
        request(
            workspace,
            "plan-propose",
            "scoped-motion-propose",
            selection=original["proposal"]["options"],
            proposal={"items": [item()]},
        )
    )
    selected = select(workspace, concept)
    visual = workspace.store("bmap").load()["revisions"][-1]["snapshot"]
    motion.apply(
        request(
            workspace,
            "plan-apply",
            "scoped-motion-apply",
            selection={
                "proposalHash": concept["proposalRef"]["sha256"],
                "decisionHash": selected["decisionRef"]["sha256"],
            },
            authoring={
                "bmap": visual,
                "tracks": canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
                "animation": strategy(),
            },
        )
    )
    current = sound_proposal(
        workspace, audio_service, original["proposal"], "sound-after-motion"
    )
    audio_request.update(
        proposalHash=current["proposalRef"]["sha256"],
        expectedBasis=current["proposal"]["basisHeads"],
    )
    result = audio_service.apply(audio_request)
    return workspace, audio_service, concept, current, result


def test_audio_only_revision_preserves_visual_direction_for_next_sound_request(
    tmp_path,
):
    workspace, service, concept, current, result = applied_motion_and_sound(tmp_path)
    assert result["status"] == "applied"
    animation = workspace.store("animation").load_index()
    assert animation["activeState"] == "stale"
    before = {
        name: workspace.artifact_path(name).read_bytes()
        for name in ("cmap", "bmap", "tracks", "animation")
    }
    snapshot = fresh_map(workspace)
    visual = next(entry for entry in snapshot["items"] if entry["itemId"] == "mo04")
    assert visual["disposition"] == "applied"
    assert snapshot["readiness"] == "stale"
    assert {
        name: workspace.artifact_path(name).read_bytes() for name in before
    } == before
    shown = MotionAuthoringService(workspace).show()
    assert shown["proposal"] == concept["proposal"]
    assert shown["status"] == "stale"
    followup = sound_proposal(
        workspace, service, deepcopy(current["proposal"]), "sound-followup"
    )
    assert followup["proposal"]["opportunities"][0]["recommendation"] == "audition"
    assert workspace.store("animation").load_index() == animation
    with pytest.raises(WorkspaceError, match="stale"):
        workspace.require_active("animation")


def test_visual_reuse_requires_current_direction_and_intact_retained_basis(tmp_path):
    workspace, _, _, _, _ = applied_motion_and_sound(tmp_path)
    shown = MotionAuthoringService(workspace).show()
    context = MotionAuthoringService.review_context(shown)
    context["directionCurrent"] = False
    snapshot = MotionReviewService(workspace).project(context)
    visual = next(entry for entry in snapshot["items"] if entry["itemId"] == "mo04")
    assert visual["disposition"] == "stale"
    context["directionCurrent"] = True
    malformed = deepcopy(context)
    malformed["proposal"]["basisHeads"]["cmap"] = "untrusted"
    snapshot = MotionReviewService(workspace).project(malformed)
    assert any(
        isinstance(gap, dict) and gap.get("kind") == "visual-reuse-unavailable"
        for gap in snapshot["gaps"]
    )
    reference = next(
        ref
        for ref in workspace.store("bmap").load_index()["revisionRefs"]
        if ref["revisionId"] == context["appliedHeads"]["bmap"]["revisionId"]
    )
    historical = workspace.timeline_dir / reference["path"]
    historical.write_bytes(b"damaged retained metadata")
    before = {
        name: workspace.artifact_path(name).read_bytes()
        for name in ("cmap", "bmap", "tracks", "animation")
    }
    snapshot = MotionReviewService(workspace).project(context)
    visual = next(entry for entry in snapshot["items"] if entry["itemId"] == "mo04")
    assert visual["disposition"] == "stale"
    assert any(
        isinstance(gap, dict) and gap.get("kind") == "visual-reuse-unavailable"
        for gap in snapshot["gaps"]
    )
    assert {
        name: workspace.artifact_path(name).read_bytes() for name in before
    } == before
