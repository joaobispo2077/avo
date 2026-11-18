"""Applied motion stays current for linked review and subsequent sound planning."""

from copy import deepcopy

from tests.test_motion_authoring import item, request, select
from tests.test_sound_proposals import prepared
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_tracks_service import canonical_tracks

from avo.timeline.animation import AnimationService
from avo.timeline.motion_authoring import MotionAuthoringService
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.sound_planning import SoundPlanningService


def test_applied_motion_keeps_its_verified_basis_for_current_sound_opportunities(
    tmp_path,
):
    workspace, catalogue, sound_request = prepared(tmp_path)
    service = MotionAuthoringService(workspace)
    proposed = service.propose(
        request(
            workspace,
            "plan-propose",
            "linked-motion-propose",
            selection=sound_request["selection"],
            proposal={"items": [item()]},
        )
    )
    immutable = deepcopy(proposed["proposal"])
    selected = select(workspace, proposed)
    visual = workspace.store("bmap").load()["revisions"][-1]["snapshot"]
    service.apply(
        request(
            workspace,
            "plan-apply",
            "linked-motion-apply",
            selection={
                "proposalHash": proposed["proposalRef"]["sha256"],
                "decisionHash": selected["decisionRef"]["sha256"],
            },
            authoring={
                "bmap": visual,
                "tracks": canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
                "animation": strategy(),
            },
        )
    )
    shown = MotionAuthoringService(workspace).show()
    assert shown["status"] == "selected" and shown["applied"] is True
    snapshot = TimelinePipeline(workspace).motion_plan()
    current = next(entry for entry in snapshot["items"] if entry["itemId"] == "mo04")
    assert current["disposition"] == "applied"
    assert snapshot["readiness"] != "stale"
    assert shown["proposal"] == immutable
    sound_request["expectedBasis"] = snapshot["basisHeads"]
    candidate = SoundPlanningService(workspace, catalogue=catalogue).propose(
        sound_request
    )
    assert candidate["proposal"]["opportunities"][0]["recommendation"] == "audition"
    after = TimelinePipeline(workspace).motion_plan()
    for key in ("basisHeads", "items", "storyboardCards", "lanes"):
        assert after[key] == snapshot[key]
    assert after["pendingRevisions"][:-1] == snapshot["pendingRevisions"]
    pending = after["pendingRevisions"][-1]
    assert pending["kind"] == "sound"
    assert pending["status"] == "awaiting-selection"
    assert pending["proposalRef"] == candidate["proposalRef"]
    AnimationService(workspace).author(
        strategy(), actor="creator", reason="A different canonical motion revision"
    )
    changed = TimelinePipeline(workspace).motion_plan()
    current = next(entry for entry in changed["items"] if entry["itemId"] == "mo04")
    assert current["disposition"] == "stale"
    assert changed["readiness"] == "stale"
    sound_request.update(
        operationId="sound-after-motion-change", expectedBasis=changed["basisHeads"]
    )
    stale = SoundPlanningService(workspace, catalogue=catalogue).propose(sound_request)
    assert stale["proposal"]["opportunities"][0]["recommendation"] == "unresolved"
