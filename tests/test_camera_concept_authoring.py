"""Camera recipes use existing concept identities and exact request history."""

from copy import deepcopy

import pytest

from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.lifecycle import PipelineRunStore
from avo.timeline.motion_authoring import MotionAuthoringError, MotionAuthoringService
from tests.test_camera_evaluator import geometry
from tests.test_motion_authoring import item, request
from tests.test_motion_authoring import select as select_concept
from tests.test_motion_authoring import workspace as authoring_workspace

workspace = pytest.fixture(name="workspace")(authoring_workspace.__wrapped__)


def camera_item(identity="mo04"):
    value = item(identity, "Emphasize the selected point")
    value.update(
        treatment="footage-emphasis",
        density=1,
        cueId=f"cue-{identity}",
        componentIds=[f"camera-{identity}"],
        cameraIntent="Use one motivated push",
        cameraRecipe={
            "preset": "push",
            "targetLayerId": "base-video",
            "sourceId": "raw-camera",
            "sourceSha256": "a" * 64,
            "sourceGeometry": geometry(),
        },
    )
    return value


def camera_request(workspace, identity="camera-first", **changes):
    return request(
        workspace,
        "plan-propose",
        identity,
        selection=resolve_editing_craft_selection(
            invocation={"camera": {"enabled": True}}
        ),
        proposal={"items": [camera_item()]},
        **changes,
    )


def test_selected_recipe_becomes_untimed_frozen_concept_and_replays_exactly(workspace):
    service = MotionAuthoringService(workspace)
    value = camera_request(workspace)
    before = deepcopy(value)
    result = service.propose(value)
    concept = result["proposal"]["items"][0]
    assert concept["label"] == "mo04"
    assert concept["cameraRecipe"] == value["proposal"]["items"][0]["cameraRecipe"]
    assert concept["cameraTreatment"]["options"] == value["selection"]
    assert concept["cameraTreatment"]["camera"]["nodes"][-1]["scale"] == 1.12
    assert service.propose(value)["proposalRef"] == result["proposalRef"]
    assert value == before
    for name in ("cmap", "bmap", "tracks", "animation"):
        assert not workspace.artifact_path(name).exists()


def test_one_camera_revision_preserves_other_ids_and_their_frozen_options(workspace):
    service = MotionAuthoringService(workspace)
    initial = camera_request(workspace)
    initial["proposal"]["items"].append(camera_item("mo05"))
    first = service.propose(initial)
    revised = camera_request(workspace, "camera-revised", newRequest=True)
    revised["selection"] = resolve_editing_craft_selection(
        invocation={"camera": {"enabled": True, "baseTreatment": "push"}}
    )
    revised["proposal"] = {
        "predecessor": first["proposalRef"]["sha256"],
        "items": deepcopy(first["proposal"]["items"]),
    }
    revised["proposal"]["items"][0]["cameraRecipe"]["preset"] = "punch-settle"
    # The caller can retain the old generated field while changing its recipe;
    # only the edited concept is regenerated from the new selected options.
    result = service.propose(revised)
    changed, retained = result["proposal"]["items"]
    assert changed["label"] == first["proposal"]["items"][0]["label"]
    assert changed["cameraTreatment"]["options"] == revised["selection"]
    assert retained == first["proposal"]["items"][1]
    assert [change["itemId"] for change in result["changes"]] == ["mo04"]


@pytest.mark.parametrize(
    "problem", ["disabled", "invalid-center", "wrong-layer", "multiple-components"]
)
def test_invalid_camera_concepts_do_not_freeze_a_run_or_publish_proposals(
    workspace, problem
):
    value = camera_request(workspace)
    concept = value["proposal"]["items"][0]
    if problem == "disabled":
        value["selection"] = resolve_editing_craft_selection()
    elif problem == "invalid-center":
        concept["cameraRecipe"]["targetCenter"] = {}
    elif problem == "wrong-layer":
        concept["cameraRecipe"]["targetLayerId"] = "unselected-layer"
    else:
        concept["componentIds"].append("another-component")
    service = MotionAuthoringService(workspace)
    with pytest.raises(MotionAuthoringError):
        service.propose(value)
    assert not workspace.pipeline_run_path.exists()
    assert not (service.root / "proposals").exists()


def test_generated_treatment_cannot_be_swapped_independently_of_its_recipe(workspace):
    service = MotionAuthoringService(workspace)
    initial = camera_request(workspace)
    first = service.propose(initial)
    before = workspace.pipeline_run_path.read_bytes()
    forged = camera_request(workspace, "camera-forged")
    forged["proposal"] = {
        "predecessor": first["proposalRef"]["sha256"],
        "items": deepcopy(first["proposal"]["items"]),
    }
    forged["proposal"]["items"][0]["cameraTreatment"]["camera"]["nodes"][-1][
        "scale"
    ] = 1.3
    with pytest.raises(MotionAuthoringError, match="recipe|treatment"):
        service.propose(forged)
    assert workspace.pipeline_run_path.read_bytes() == before


@pytest.mark.parametrize("enabled", [False, True])
def test_new_camera_concept_uses_active_request_options_until_explicitly_replaced(
    workspace, enabled
):
    selection = resolve_editing_craft_selection(
        invocation={"camera": {"enabled": enabled}}
    )
    initial = request(
        workspace,
        "plan-propose",
        "freeze-options",
        selection=selection,
        proposal={"items": [item()]},
    )
    service = MotionAuthoringService(workspace)
    service.propose(initial)
    before = workspace.pipeline_run_path.read_bytes()
    original_run = PipelineRunStore(workspace.pipeline_run_path).load()
    value = camera_request(workspace, "new-concept-same-request")
    value["selection"] = resolve_editing_craft_selection(
        invocation={"camera": {"enabled": True, "baseTreatment": "push"}}
    )
    if enabled:
        result = service.propose(value)
        assert result["proposal"]["items"][0]["cameraTreatment"]["options"] == selection
        assert result["proposal"]["options"] == selection
        updated = PipelineRunStore(workspace.pipeline_run_path).load()
        assert updated["extensions"]["editingCraftWork"].pop() == {
            "kind": "motion",
            "operationId": value["operationId"],
            "requestId": result["proposal"]["requestId"],
            "proposalRef": result["proposalRef"],
            "scope": {"itemIds": ["mo04"], "eventIds": []},
        }
        updated["updatedAt"] = original_run["updatedAt"]
        assert updated == original_run
    else:
        with pytest.raises(MotionAuthoringError, match="enabled options"):
            service.propose(value)
        assert workspace.pipeline_run_path.read_bytes() == before


@pytest.mark.parametrize("change", ["path", "options", "omitted"])
def test_timed_authoring_cannot_replace_a_selected_camera_treatment(workspace, change):
    workspace.initialize()
    service = MotionAuthoringService(workspace)
    proposed = service.propose(camera_request(workspace))
    select_concept(workspace, proposed)
    component = {
        "componentId": "camera-mo04",
        "extensions": {
            "editingCraft": deepcopy(
                proposed["proposal"]["items"][0]["cameraTreatment"]
            )
        },
    }
    authoring = {"animation": {"components": [component]}}
    service._scope(service.show(), authoring)
    if change == "path":
        component["extensions"]["editingCraft"]["camera"]["nodes"][-1]["scale"] = 1.3
    elif change == "options":
        component["extensions"]["editingCraft"]["options"] = (
            resolve_editing_craft_selection()
        )
    else:
        authoring["animation"]["components"] = []
    with pytest.raises(MotionAuthoringError, match="selected camera|camera treatment"):
        service._scope(service.show(), authoring)
    assert workspace.store("animation").load_index()["headRevisionId"] is None


def test_static_motion_selection_cannot_inject_an_enabled_camera_component(workspace):
    from avo.timeline.camera import make_camera_treatment
    from tests.test_motion_authoring import propose

    workspace.initialize()
    proposed, _ = propose(workspace)
    select_concept(workspace, proposed)
    wrapper = make_camera_treatment(
        "push",
        target_layer_id="base-video",
        source_id="raw-camera",
        source_sha256="a" * 64,
        geometry=geometry(),
        options=resolve_editing_craft_selection(
            invocation={"camera": {"enabled": True}}
        ),
    )
    authoring = {
        "animation": {
            "components": [
                {"componentId": "chapter-pair", "extensions": {"editingCraft": wrapper}}
            ]
        }
    }
    with pytest.raises(MotionAuthoringError, match="selected camera|camera selection"):
        MotionAuthoringService(workspace)._scope(
            MotionAuthoringService(workspace).show(), authoring
        )
    assert workspace.store("animation").load_index()["headRevisionId"] is None
