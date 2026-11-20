"""Explicit cue references link legacy motion items without overriding canonical identity."""

from copy import deepcopy

from avo.timeline.bmap_service import BMapService
from avo.timeline.motion_review import MotionReviewService
from tests.test_motion_authoring import item
from tests.test_timeline_bmap_service import approved_workspace, cue


def projected(tmp_path, concepts, *, canonical_id=None):
    workspace, _, _ = approved_workspace(tmp_path)
    visual = cue()
    if canonical_id is not None:
        visual["contentRef"]["itemId"] = canonical_id
    BMapService(workspace).author(
        {"cues": [visual]}, actor="fixture", reason="Existing canonical cue"
    )
    before = workspace.store("bmap").load_index()
    snapshot = MotionReviewService(workspace).project(
        {"proposal": {"items": deepcopy(concepts)}}
    )
    assert workspace.store("bmap").load_index() == before
    return snapshot, visual


def test_unique_explicit_cue_reference_links_map_and_storyboard_without_rewriting_source(
    tmp_path,
):
    snapshot, original = projected(tmp_path, [item()])
    assert [row["itemId"] for row in snapshot["items"]] == ["mo04"]
    assert [row["itemId"] for row in snapshot["storyboardCards"]] == ["mo04"]
    current = snapshot["items"][0]
    assert current["timingState"] == "timed"
    assert current["parts"][0]["cue"] == original
    assert "itemId" not in original["contentRef"]
    assert snapshot["storyboardCards"][0]["evidence"]["status"] == "unverified"


def test_two_item_claims_keep_one_canonical_contribution_and_flag_all_affected_items(
    tmp_path,
):
    snapshot, _ = projected(tmp_path, [item(), item("mo05")])
    assert sum(len(row["parts"]) for row in snapshot["items"]) == 1
    assert all(row["identityConflicts"] for row in snapshot["items"])
    assert snapshot["readiness"] == "needs-judgment"
    assert any(
        isinstance(gap, dict) and gap.get("kind") == "cue-item-identity-conflict"
        for gap in snapshot["gaps"]
    )


def test_existing_canonical_item_identity_wins_over_a_conflicting_proposal(tmp_path):
    snapshot, _ = projected(tmp_path, [item()], canonical_id="canonical-one")
    with_parts = [row for row in snapshot["items"] if row["parts"]]
    assert [row["itemId"] for row in with_parts] == ["canonical-one"]
    assert with_parts[0]["identityConflicts"]
    assert snapshot["readiness"] == "needs-judgment"


def test_malformed_canonical_item_identity_becomes_an_explicit_unavailable_gap(
    tmp_path,
):
    snapshot, _ = projected(tmp_path, [], canonical_id={"untrusted": "identity"})
    assert snapshot["readiness"] == "unavailable"
    assert snapshot["items"] == []
    assert any(
        isinstance(gap, dict)
        and gap.get("kind") == "artifact-unavailable"
        and gap.get("artifact") == "bmap"
        for gap in snapshot["gaps"]
    )
