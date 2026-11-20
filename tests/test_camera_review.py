"""Selected numeric camera intent never claims observed or approved frames."""

from copy import deepcopy

import pytest

from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.contracts import content_hash
from avo.timeline.motion_authoring import MotionAuthoringService
from avo.timeline.motion_review import MotionReviewService
from tests.test_camera_concept_authoring import camera_request
from tests.test_motion_review_projection import cue, install
from tests.test_motion_review_projection import workspace as review_workspace
from tests.test_timeline_animation_service import strategy

workspace = pytest.fixture(name="workspace")(review_workspace.__wrapped__)


def test_camera_concept_has_path_states_without_media_inspection(
    workspace, monkeypatch
):
    proposed = MotionAuthoringService(workspace).propose(camera_request(workspace))

    def forbidden(*args, **kwargs):
        pytest.fail("Camera review inspected media or runtime")

    monkeypatch.setattr("avo.timeline.contracts.file_fingerprint", forbidden)
    monkeypatch.setattr(
        "avo.adapters.media.camera_provenance.camera_runtime_identity", forbidden
    )
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    snapshot = MotionReviewService(workspace).project(
        {"proposal": proposed["proposal"]}
    )
    item, card = snapshot["items"][0], snapshot["storyboardCards"][0]
    camera = item["camera"]
    assert camera["state"] == "planned"
    assert camera["sourceId"] == "raw-camera"
    wrapper = proposed["proposal"]["items"][0]["cameraTreatment"]
    assert camera["pathHash"] == content_hash(
        {"behavior": wrapper["camera"], "geometry": wrapper["sourceGeometry"]}
    )
    assert camera["optionsHash"] == content_hash(wrapper["options"])
    assert card["camera"]["before"] == camera["before"]
    assert card["camera"]["during"]["nodes"] == wrapper["camera"]["nodes"]
    assert card["camera"]["after"]["scale"] == 1.12
    assert item["timing"] is None
    assert card["evidence"]["status"] == "unverified"
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize("available", [True, False])
def test_pending_face_intent_shows_preparation_in_linked_views(
    workspace, monkeypatch, available
):
    monkeypatch.setattr(
        "avo.timeline.face_analysis._face_pin_present", lambda workspace: available
    )
    selection = resolve_editing_craft_selection(
        invocation={"camera": {"enabled": True, "faceAnchor": "selected-subject"}}
    )
    item = {"itemId": "presenter", "cameraIntent": "Hold framing on this speaker"}
    result = MotionReviewService(workspace).project(
        {"proposal": {"items": [item], "options": selection}}
    )
    view = result["items"][0]["camera"]["during"]["faceAnchor"]
    assert result["storyboardCards"][0]["camera"]["during"]["faceAnchor"] == view
    assert view["status"] == (
        "subject-selection-required" if available else "capability-unavailable"
    )


@pytest.mark.parametrize("link", ["content", "explicit", "single", "ambiguous"])
def test_camera_component_joins_only_an_unambiguous_reference(
    workspace, monkeypatch, link
):
    proposed = MotionAuthoringService(workspace).propose(camera_request(workspace))
    wrapper = proposed["proposal"]["items"][0]["cameraTreatment"]
    data, context = cue(), None
    if link == "content":
        data["contentRef"]["componentId"] = "camera-mo04"
    elif link == "explicit":
        data["componentRef"] = "camera-mo04"
    else:
        identifiers = ["camera-mo04"] if link == "single" else ["camera-mo04", "other"]
        context = {
            "proposal": {"items": [{"itemId": "mo04", "componentIds": identifiers}]}
        }
        if link == "ambiguous":
            context["proposal"]["items"][0]["_authoredCamera"] = deepcopy(wrapper)
    animation = strategy()
    animation["dependencies"] = dict.fromkeys(("cmap", "bmap", "tracks"), "a" * 64)
    animation["strategyContractVersion"] = "2.0.0"
    animation["components"][0].update(
        componentId="camera-mo04", extensions={"editingCraft": deepcopy(wrapper)}
    )
    install(
        workspace,
        monkeypatch,
        {
            "bmap": {"cues": [data]},
            "animation": animation,
        },
    )
    snapshot = MotionReviewService(workspace).project(context)
    item, card = snapshot["items"][0], snapshot["storyboardCards"][0]
    if link == "ambiguous":
        assert item["camera"] is None
        return
    assert item["camera"]["state"] == "authored"
    assert item["componentRef"] == "camera-mo04"
    assert card["camera"]["after"]["scale"] == 1.12
    assert card["evidence"]["status"] == "unverified"
