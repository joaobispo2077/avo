"""Pure source-picture framing uses original clocks, never prior seek state."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction

import pytest

from avo.timeline.camera import (
    CameraError,
    display_size,
    ease_curve,
    evaluate_camera,
    validate_camera_schedule,
)
from avo.timeline.contracts import ContractError, validate_document


def geometry(**changes):
    return {
        "codedWidth": 1920,
        "codedHeight": 1080,
        "sampleAspectRatio": {"num": 1, "den": 1},
        "rotationDegrees": 0,
        "baselineCrop": {"x": 0, "y": 0, "width": 1920, "height": 1080},
        **changes,
    }


def node(phase, scale=1, *, x=0.5, y=0.5, curve="linear"):
    return {"phase": phase, "scale": scale, "center": {"x": x, "y": y}, "curve": curve}


def behavior(nodes=None, **changes):
    return {
        "contractVersion": "1.0.0",
        "targetLayerId": "source-main",
        "nodes": nodes or [node(0), node(1, 2)],
        **changes,
    }


def sample(path=None, frame=100, *, first=100, end=110, source=None, predecessor=None):
    return evaluate_camera(
        path or behavior(),
        frame=frame,
        frame_range={"firstFrame": first, "endFrameExclusive": end},
        geometry=source or geometry(),
        predecessor=predecessor,
    )


def test_exact_first_and_final_samples_use_n_minus_one_not_n():
    first = sample(frame=100)
    final = sample(frame=109)
    assert first["scale"] == 1
    assert first["crop"] == {"x": 0, "y": 0, "width": 1920, "height": 1080}
    assert final["scale"] == 2
    assert final["crop"] == {"x": 480, "y": 270, "width": 960, "height": 540}
    assert sample(frame=101)["scale"] == pytest.approx(1 + 1 / 9)


@pytest.mark.parametrize("count", [2, 3, 30, 300])
def test_every_nontrivial_interval_reaches_actual_endpoints(count):
    path = behavior([node(0, 1.1), node(1, 1.7)])
    assert sample(path, 73, first=73, end=73 + count)["scale"] == 1.1
    assert sample(path, 72 + count, first=73, end=73 + count)["scale"] == 1.7


def test_one_frame_interval_can_hold_only():
    held = behavior([node(0, 1.25), node(1, 1.25, curve="hold")])
    assert sample(held, frame=42, first=42, end=43)["scale"] == 1.25
    with pytest.raises(CameraError, match="one.frame|hold"):
        sample(frame=42, first=42, end=43)


def test_before_after_and_backward_seeks_use_declared_actual_states():
    path = behavior([node(0, 1.2, x=0.48), node(1, 1.8, x=0.55)])
    order = [109, 100, 105, 101, 108, 99, 110, 105]
    snapshots = {frame: sample(path, frame) for frame in order}
    assert snapshots[99]["scale"] == 1.2
    assert snapshots[99]["center"] == {"x": 0.48, "y": 0.5}
    assert snapshots[110]["scale"] == 1.8
    assert snapshots[110]["center"] == {"x": 0.55, "y": 0.5}
    assert [sample(path, frame) for frame in order] == [
        snapshots[frame] for frame in order
    ]


def test_window_and_split_samples_keep_original_full_interval():
    path = behavior([node(0, 1.1, curve="quadratic-in-out"), node(1, 1.8)])
    full = [sample(path, frame, first=1000, end=1030) for frame in range(1000, 1030)]
    window = [sample(path, frame, first=1000, end=1030) for frame in range(1010, 1018)]
    assert window == full[10:18]
    pieces = [sample(path, frame, first=1000, end=1030) for frame in range(1000, 1013)]
    pieces += [sample(path, frame, first=1000, end=1030) for frame in range(1013, 1030)]
    assert pieces == full


def test_rational_ntsc_clock_does_not_rebase_or_accumulate_rounding():
    rate = Fraction(30000, 1001)
    first_time = Fraction(1001, 30)
    first_frame = first_time * rate
    assert first_frame == 1000
    last = Fraction(1029, 1) / rate
    assert last * rate == 1029
    assert (
        sample(frame=int(last * rate), first=int(first_frame), end=1030)["scale"] == 2
    )


@pytest.mark.parametrize(
    "rotation,size",
    [(0, (768, 576)), (90, (576, 768)), (180, (768, 576)), (270, (576, 768))],
)
def test_display_geometry_applies_sar_before_orientation(rotation, size):
    source = geometry(
        codedWidth=720,
        codedHeight=576,
        sampleAspectRatio={"num": 16, "den": 15},
        rotationDegrees=rotation,
    )
    assert display_size(source) == tuple(map(Fraction, size))


def test_fractional_display_width_is_not_rounded_to_raw_or_output_width():
    source = geometry(
        codedWidth=854,
        codedHeight=480,
        sampleAspectRatio={"num": 4, "den": 3},
        baselineCrop={"x": 10, "y": 20, "width": 1000, "height": 400},
    )
    assert display_size(source) == (Fraction(3416, 3), Fraction(480))
    returned = sample(behavior([node(0, 1.4), node(1)]), frame=109, source=source)
    assert returned["crop"] == source["baselineCrop"]


def test_scale_one_restores_noncentered_declared_baseline():
    baseline = {"x": 120, "y": 40, "width": 1280, "height": 720}
    source = geometry(baselineCrop=baseline)
    path = behavior([node(0, 1.4, x=0.55), node(1)])
    assert sample(path, frame=109, source=source)["crop"] == baseline


@pytest.mark.parametrize(
    "name,phase,expected",
    [
        ("linear", 0.25, 0.25),
        ("quadratic-in", 0.5, 0.25),
        ("quadratic-out", 0.5, 0.75),
        ("quadratic-in-out", 0.25, 0.125),
        ("quadratic-in-out", 0.75, 0.875),
        ("quartic-in", 0.5, 0.0625),
        ("exponential-out", 0.5, 0.96875),
        ("hold", 0.75, 0),
    ],
)
def test_named_curve_v1_numeric_contract(name, phase, expected):
    assert ease_curve(name, Fraction(str(phase))) == pytest.approx(expected)
    assert ease_curve(name, Fraction(0)) == 0
    assert ease_curve(name, Fraction(1)) == 1
    assert all(0 <= ease_curve(name, Fraction(index, 100)) <= 1 for index in range(101))


def test_no_arbitrary_expression_nonfinite_or_invalid_path_values():
    for curve in ("Math.sin(t)", "eval('x')", "cubic-bezier(9,-2,4,7)"):
        with pytest.raises(CameraError):
            ease_curve(curve, Fraction(1, 2))
    for value in (float("nan"), float("inf"), -1, 2, True):
        with pytest.raises(CameraError):
            ease_curve("linear", value)
    for nodes in (
        [node(0.5), node(1)],
        [node(0), node(0)],
        [node(0), node(1, float("inf"))],
        [node(0), node(1, -1)],
    ):
        with pytest.raises(CameraError):
            sample(behavior(nodes))


def test_predecessor_continuity_binds_both_scale_and_actual_center():
    prior = {"scale": 1.4, "center": {"x": 0.55, "y": 0.5}}
    continuation = behavior([node(0, 1.4, x=0.55), node(1, 1.2)])
    assert sample(continuation, predecessor=prior)["scale"] == prior["scale"]
    for changed in (
        {"scale": 1.3, "center": prior["center"]},
        {"scale": 1.4, "center": {"x": 0.5, "y": 0.5}},
    ):
        with pytest.raises(CameraError, match="predecessor|continuity"):
            sample(continuation, predecessor=changed)


def test_crop_bounds_and_declared_display_margins_checked_at_every_sample():
    with pytest.raises(CameraError, match="bound|margin|crop"):
        sample(behavior([node(0, 1.2, x=0), node(1, 1.2, x=0)]))
    source = geometry(cropMargin={"left": 10, "right": 10, "top": 10, "bottom": 10})
    with pytest.raises(CameraError, match="bound|margin|crop"):
        sample(behavior([node(0), node(1)]), source=source)
    assert sample(behavior([node(0, 1.2), node(1, 1.2)]), source=source)["scale"] == 1.2


def test_declared_source_safe_region_must_remain_visible_with_clearance():
    region = {
        "regionId": "evidence",
        "coordinateSpace": "display-normalized",
        "rect": {"x": 0.1, "y": 0.4, "width": 0.1, "height": 0.1},
        "clearance": 0.02,
    }
    protected = behavior([node(0), node(1, 2)], safeRegions=[region])
    assert sample(protected, frame=100)["scale"] == 1
    with pytest.raises(CameraError, match="safe|protect|region"):
        sample(protected, frame=109)


def test_safe_region_clearance_is_enforced_independently_of_containment():
    region = {
        "regionId": "edge",
        "coordinateSpace": "display-normalized",
        "rect": {"x": 0.25, "y": 0.45, "width": 0.05, "height": 0.1},
        "clearance": 0,
    }
    path = behavior([node(0, 2), node(1, 2)], safeRegions=[region])
    assert sample(path)["scale"] == 2
    path["safeRegions"][0]["clearance"] = 0.02
    with pytest.raises(CameraError, match="safe|protect|region"):
        sample(path)


def test_unsupported_numeric_output_fails_as_a_camera_error():
    too_large = 10**500
    with pytest.raises(CameraError):
        sample(behavior([node(0, too_large), node(1, too_large)]))


def move(move_id, path=None, *, first=100, end=110, owners=None):
    return {
        "moveId": move_id,
        "behavior": path or behavior(),
        "frameRange": {"firstFrame": first, "endFrameExclusive": end},
        "propertyOwners": owners or {"scale": move_id, "center": move_id},
    }


def test_schedule_rejects_simultaneous_same_layer_owners_and_conflicting_properties():
    with pytest.raises(CameraError, match="overlap|owner"):
        validate_camera_schedule(
            [move("a"), move("b", first=105, end=115)], geometry=geometry()
        )
    with pytest.raises(CameraError, match="owner"):
        validate_camera_schedule(
            [move("a", owners={"scale": "a", "center": "b"})], geometry=geometry()
        )
    other = behavior(targetLayerId="other-source")
    validate_camera_schedule([move("a"), move("b", other)], geometry=geometry())


def test_schedule_validates_intermediate_nodes_and_keeps_adjacent_handoff():
    illegal_middle = behavior([node(0, 1.2), node(0.5, 1.2, x=0), node(1, 1.2)])
    with pytest.raises(CameraError, match="bound|margin|crop"):
        validate_camera_schedule(
            [move("bad", illegal_middle, end=111)], geometry=geometry()
        )
    entering = behavior([node(0), node(1, 1.4)])
    leaving = behavior([node(0, 1.4), node(1)])
    validate_camera_schedule(
        [move("a", entering), move("b", leaving, first=110, end=120)],
        geometry=geometry(),
    )


def test_behavior_schema_is_strict_relative_and_does_not_mutate_inputs():
    path = behavior(
        safeRegions=[
            {
                "regionId": "subject",
                "coordinateSpace": "display-normalized",
                "rect": {"x": 0.45, "y": 0.45, "width": 0.1, "height": 0.1},
                "clearance": 0,
            }
        ]
    )
    before = deepcopy(path)
    validate_document(path, "avo.camera-behavior.schema.json")
    sample(path)
    assert path == before
    for forbidden in ("start", "end", "timing", "outputFrame", "expression"):
        changed = {**path, forbidden: 0}
        with pytest.raises(ContractError):
            validate_document(changed, "avo.camera-behavior.schema.json")
