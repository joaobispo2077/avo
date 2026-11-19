"""Selected camera recipes remain untimed and start from actual source framing."""

from copy import deepcopy

import pytest

from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.camera import CameraError, evaluate_camera, make_camera_treatment
from avo.timeline.contracts import validate_document
from tests.test_camera_evaluator import geometry


def options(**camera):
    return resolve_editing_craft_selection(
        invocation={"camera": {"enabled": True, **camera}}
    )


def treatment(name, **changes):
    return make_camera_treatment(
        name,
        target_layer_id="presenter",
        source_id="raw-camera",
        source_sha256="a" * 64,
        geometry=geometry(),
        options=changes.pop("options", options()),
        **changes,
    )


def state(selected, frame):
    return evaluate_camera(
        selected["camera"],
        frame=frame,
        frame_range={"firstFrame": 0, "endFrameExclusive": 101},
        geometry=selected["sourceGeometry"],
    )


def test_camera_recipes_require_explicit_enabled_options():
    with pytest.raises(CameraError, match="selected|enabled"):
        treatment("push", options=resolve_editing_craft_selection())
    with pytest.raises(CameraError, match="face|trajectory"):
        treatment("push", options=options(faceAnchor="selected-subject"))


@pytest.mark.parametrize("name", ["push", "punch-settle", "speed-contrast"])
def test_push_recipes_preserve_actual_entry_and_selected_source(name):
    predecessor = {"scale": 1.08, "center": {"x": 0.48, "y": 0.5}}
    before = deepcopy(predecessor)
    selected = treatment(name, predecessor=predecessor, target_scale=1.2)
    validate_document(selected, "avo.animation.schema.json#/$defs/editingCraft")
    assert state(selected, 0)["scale"] == 1.08
    assert state(selected, 0)["center"] == predecessor["center"]
    assert selected["camera"]["sourceId"] == "raw-camera"
    assert selected["camera"]["targetLayerId"] == "presenter"
    assert selected["sourceSha256"] == "a" * 64
    assert selected["entryPolicy"] == "continuous"
    assert predecessor == before
    for frame in range(101):
        assert 1.08 <= state(selected, frame)["scale"] <= 1.2
    if name == "punch-settle":
        scales = [state(selected, frame)["scale"] for frame in range(101)]
        assert max(scales) == 1.2
        assert 1.08 < scales[-1] < max(scales)
    else:
        assert state(selected, 100)["scale"] == 1.2


def test_pull_and_overlay_return_restore_the_declared_baseline():
    predecessor = {"scale": 1.2, "center": {"x": 0.48, "y": 0.5}}
    for name in ("pull", "overlay-return"):
        selected = treatment(name, predecessor=predecessor)
        assert state(selected, 0)["scale"] == 1.2
        assert state(selected, 100)["crop"] == geometry()["baselineCrop"]
    returned = treatment("overlay-return", predecessor=predecessor)
    for key in ("scale", "center", "crop"):
        assert state(returned, 75)[key] == state(returned, 100)[key]


def test_cut_to_close_requests_an_actual_source_cut_without_fake_continuity():
    selected = treatment("cut-to-close", target_scale=1.2)
    assert selected["entryPolicy"] == "source-cut"
    assert state(selected, 0)["scale"] == state(selected, 100)["scale"] == 1.2


def test_section_alternation_and_drift_require_their_selected_base_treatment():
    for name in ("section-alternate", "section-drift"):
        with pytest.raises(CameraError, match="base|selected"):
            treatment(name)
    alternating = options(baseTreatment="alternate")
    close = treatment("section-alternate", options=alternating)
    wide = treatment(
        "section-alternate", options=alternating, predecessor=state(close, 100)
    )
    assert state(close, 0)["scale"] > 1
    assert state(wide, 0)["scale"] == 1
    assert close["entryPolicy"] == wide["entryPolicy"] == "source-cut"
    drifting = treatment("section-drift", options=options(baseTreatment="push"))
    assert 1 < state(drifting, 100)["scale"] <= 1.05


def test_recipe_generation_preserves_frozen_options_and_has_no_output_timing():
    selection = options()
    before = deepcopy(selection)
    selected = treatment("push", options=selection)
    assert selected["options"] == before
    selected["options"]["effective"]["camera"]["enabled"] = False
    assert selection == before
    for node in selected["camera"]["nodes"]:
        assert set(node) == {"phase", "scale", "center", "curve"}
    assert set(selected) == {
        "camera",
        "sourceGeometry",
        "sourceSha256",
        "options",
        "entryPolicy",
    }


@pytest.mark.parametrize("scale", [0, -1, True, float("inf"), float("nan"), "1.2"])
def test_non_numeric_or_invalid_camera_targets_are_rejected(scale):
    with pytest.raises(CameraError):
        treatment("push", target_scale=scale)


@pytest.mark.parametrize(
    "center",
    [{}, False, [], {"x": 0.5}, {"x": 0.5, "y": 0.5, "expression": "untrusted"}],
)
def test_explicit_invalid_target_centers_are_not_replaced_or_silently_trimmed(center):
    with pytest.raises(CameraError):
        treatment("push", target_center=center)


def test_camera_recipe_cannot_crop_protected_source_content():
    protected = [
        {
            "regionId": "evidence",
            "coordinateSpace": "display-normalized",
            "rect": {"x": 0, "y": 0, "width": 0.1, "height": 0.1},
            "clearance": 0,
        }
    ]
    with pytest.raises(CameraError, match="protected|safe region"):
        treatment("push", target_scale=1.2, safe_regions=protected)
