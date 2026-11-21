"""Selected camera paths compile from the one cue clock onto original contributions."""

from copy import deepcopy

import pytest

from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.camera import CameraError, evaluate_camera, reframe_face_camera

SHA = "a" * 64


def geometry():
    return {
        "codedWidth": 1280,
        "codedHeight": 720,
        "rotationDegrees": 0,
        "sampleAspectRatio": {"num": 1, "den": 1},
        "baselineCrop": {"x": 0, "y": 0, "width": 1280, "height": 720},
    }


def detected_face(tick, x):
    return {
        "sourceTick": tick,
        "box": [x, 0.35, 0.2, 0.3],
        "center": {"x": x + 0.1, "y": 0.5},
    }


def test_frozen_face_reframes_original_video_with_continuous_entry_and_release():
    behavior = component()["extensions"]["editingCraft"]["camera"]
    interval = {"firstFrame": 30, "endFrameExclusive": 37}
    trusted = [detected_face(120, 0.51), detected_face(126, 0.57)]
    anchored = reframe_face_camera(
        behavior,
        frame_range=interval,
        geometry=geometry(),
        points=trusted,
        source_ticks=range(120, 127),
        transition_frames=2,
        fallback="review",
    )

    def seek(frame, path=anchored):
        return evaluate_camera(
            path, frame=frame, frame_range=interval, geometry=geometry()
        )

    middle = seek(33)
    assert seek(36) == seek(36, behavior)
    assert seek(30) == seek(30, behavior)
    assert middle["scale"] == seek(33, behavior)["scale"]
    assert middle["center"]["x"] > 0.5
    assert seek(33) == middle


@pytest.mark.parametrize("fallback", ["review", "hold", "static"])
def test_frozen_face_requires_selected_uncertain_interval_behavior(fallback):
    behavior = component()["extensions"]["editingCraft"]["camera"]
    interval = {"firstFrame": 30, "endFrameExclusive": 37}
    arguments = {
        "frame_range": interval,
        "geometry": geometry(),
        "points": [detected_face(120, 0.51), detected_face(123, 0.57)],
        "source_ticks": range(120, 127),
        "transition_frames": 2,
        "fallback": fallback,
    }
    if fallback == "review":
        with pytest.raises(CameraError, match="reviewed fallback"):
            reframe_face_camera(behavior, **arguments)
        return
    path = reframe_face_camera(behavior, **arguments)
    latest = evaluate_camera(path, frame=36, frame_range=interval, geometry=geometry())
    prior = evaluate_camera(path, frame=33, frame_range=interval, geometry=geometry())
    if fallback == "hold":
        assert latest["crop"] == prior["crop"]
    else:
        assert latest["scale"] == 1
        assert latest["center"] == {"x": 0.5, "y": 0.5}


def component(identity="camera-push", *, first=1, last=1.2, entry="continuous"):
    return {
        "componentId": identity,
        "extensions": {
            "editingCraft": {
                "camera": {
                    "contractVersion": "1.0.0",
                    "targetLayerId": "presenter",
                    "sourceId": "camera-main",
                    "nodes": [
                        {
                            "phase": 0,
                            "scale": first,
                            "center": {"x": 0.5, "y": 0.5},
                            "curve": "quadratic-in-out",
                        },
                        {
                            "phase": 1,
                            "scale": last,
                            "center": {"x": 0.5, "y": 0.5},
                            "curve": "hold",
                        },
                    ],
                },
                "sourceGeometry": geometry(),
                "sourceSha256": SHA,
                "entryPolicy": entry,
            }
        },
    }


def cue(identity, start, end):
    clock = {"timebase": {"num": 1, "den": 30}, "domain": "cmap-output"}
    return {
        "cueId": "cue-" + identity,
        "start": {"ticks": start, **clock},
        "end": {"ticks": end, **clock},
        "targetLayerId": "presenter",
        "contentRef": {"componentId": identity},
    }


def contribution(identity="take-one", first=0, last=60):
    return {
        "operationId": identity,
        "kind": "trim",
        "inputs": ["camera-main"],
        "outputRange": {"startFrame": first, "endFrameExclusive": last},
        "parameters": {
            "sourceId": "camera-main",
            "source": {
                "sha256": SHA,
                "mediaClass": "source",
                "locator": "declared-original.mp4",
            },
            "sourceRange": {
                "startTicks": 0,
                "endTicks": last - first,
                "timebase": {"num": 1, "den": 30},
            },
        },
    }


def compile_moves(
    *, components=None, cues=None, operations=None, selection=None, read_face=None
):
    from avo.timeline.camera_plan import compile_camera_operations

    return compile_camera_operations(
        {"components": components or [component()]},
        bmap={"cues": cues or [cue("camera-push", 0, 30)]},
        tracks={
            "videoTracks": {
                "layers": [
                    {
                        "layerId": "presenter",
                        "role": "base",
                        "source": {"sha256": SHA},
                        "regions": [{"cueIds": ["cue-camera-push", "cue-camera-pull"]}],
                    }
                ]
            }
        },
        video_graph={"operations": operations or [contribution()]},
        output={"frameRate": {"num": 30, "den": 1}},
        selection=selection
        or resolve_editing_craft_selection(invocation={"camera": {"enabled": True}}),
        read_face=read_face,
    )


def test_split_repeated_original_occurrences_keep_the_original_full_cue_clock():
    operations = compile_moves(
        operations=[
            contribution("first-occurrence", 0, 12),
            contribution("repeated-occurrence", 12, 60),
        ]
    )
    assert len(operations) == 2
    assert {op["parameters"]["sourceOccurrenceId"] for op in operations} == {
        "first-occurrence",
        "repeated-occurrence",
    }
    assert all(
        op["parameters"]["originalFrameRange"]
        == {"firstFrame": 0, "endFrameExclusive": 30}
        for op in operations
    )
    parameters = operations[1]["parameters"]
    at_split = evaluate_camera(
        parameters["behavior"],
        frame=12,
        frame_range=parameters["originalFrameRange"],
        geometry=parameters["geometry"],
    )
    assert 1 < at_split["scale"] < 1.2
    assert parameters["sourceSha256"] == SHA
    assert parameters["optionsHash"]


def test_moves_emit_holds_until_the_next_move_and_retain_exact_predecessors():
    operations = compile_moves(
        components=[component(), component("camera-pull", first=1.2, last=1)],
        cues=[cue("camera-push", 0, 10), cue("camera-pull", 20, 30)],
    )
    assert [op["outputRange"] for op in operations] == [
        {"startFrame": 0, "endFrameExclusive": 20},
        {"startFrame": 20, "endFrameExclusive": 60},
    ]
    first = operations[0]["parameters"]
    assert (
        evaluate_camera(
            first["behavior"],
            frame=19,
            frame_range=first["originalFrameRange"],
            geometry=first["geometry"],
        )["scale"]
        == 1.2
    )
    assert operations[1]["parameters"]["entryState"]["scale"] == 1.2


@pytest.mark.parametrize(
    "failure",
    [
        "disabled",
        "wrong-source",
        "wrong-layer",
        "retimed",
        "unresolved-geometry",
        "unselected-face",
    ],
)
def test_unqualified_camera_inputs_stop_before_output_operations(failure):
    values, operations, selection = [component()], [contribution()], None
    if failure == "disabled":
        selection = resolve_editing_craft_selection()
    elif failure == "wrong-source":
        operations[0]["parameters"]["source"]["sha256"] = "b" * 64
    elif failure == "wrong-layer":
        values[0]["extensions"]["editingCraft"]["camera"]["targetLayerId"] = "other"
    elif failure == "retimed":
        operations[0]["parameters"]["sourceRange"]["endTicks"] = 30
    elif failure == "unresolved-geometry":
        values[0]["extensions"]["editingCraft"].pop("sourceGeometry")
    else:
        selection = resolve_editing_craft_selection(
            invocation={"camera": {"enabled": True, "faceAnchor": "selected-subject"}}
        )
    with pytest.raises(CameraError):
        compile_moves(components=values, operations=operations, selection=selection)


def test_cut_to_close_requires_an_actual_visible_source_cut_boundary():
    assert compile_moves(
        components=[component(first=1.2, last=1.2, entry="source-cut")]
    )
    with pytest.raises(CameraError, match="cut"):
        compile_moves(
            components=[component(first=1.2, last=1.2, entry="source-cut")],
            cues=[cue("camera-push", 5, 30)],
        )


def test_unmotivated_entry_and_same_layer_overlapping_owners_are_rejected():
    with pytest.raises(CameraError, match="predecessor|entry"):
        compile_moves(components=[component(first=1.1)])
    with pytest.raises(CameraError, match="overlap|owner"):
        compile_moves(
            components=[component(), component("camera-pull", first=1.2, last=1)],
            cues=[cue("camera-push", 0, 30), cue("camera-pull", 20, 40)],
        )


def test_hidden_or_missing_cues_do_not_force_camera_or_effects_on_other_content():
    with pytest.raises(CameraError, match="cue|visible|source"):
        compile_moves(cues=[cue("different-component", 0, 30)])


def test_compilation_is_deterministic_and_keeps_inputs_unchanged():
    value = component()
    original = deepcopy(value)
    assert compile_moves(components=[value]) == compile_moves(components=[value])
    assert value == original


@pytest.mark.parametrize(
    "failure", [None, "missing-review", "wrong-stream", "crosses-cut", "range"]
)
def test_face_camera_joins_exact_source_origin_and_visible_occurrence(failure):
    item = component()
    camera = item["extensions"]["editingCraft"]
    camera["faceAnchor"] = {
        "observationRef": {"locator": f"edit/motion/face/{SHA}.json", "sha256": SHA},
        "trajectoryHash": SHA,
        "transitionFrames": 2,
        "fallbackReview": {
            "actor": "creator",
            "reason": "Hold the confirmed final framing",
        },
    }
    source = contribution("visible", 20, 30)
    source["parameters"]["source"]["streamIndex"] = 2
    source["parameters"]["sourceRange"].update(startTicks=3, endTicks=13)
    trajectory = {
        "streamOriginTicks": 3000,
        "sourceRange": {
            "startTicks": 3000,
            "endTicks": 3121,
            "timebase": {"num": 1, "den": 300},
        },
        "points": [detected_face(3050, 0.51), detected_face(3090, 0.57)],
    }
    selection = resolve_editing_craft_selection(
        invocation={
            "camera": {
                "enabled": True,
                "faceAnchor": "selected-subject",
                "onLost": "hold",
            }
        }
    )
    cuts = [source, contribution("later", 30, 60)]
    arguments = {
        "components": [item],
        "cues": [cue("camera-push", 22, 29)],
        "operations": cuts,
        "selection": selection,
        "read_face": lambda value: (trajectory, 2),
    }
    if failure == "missing-review":
        camera["faceAnchor"].pop("fallbackReview")
        message = "reviewed fallback"
    elif failure == "wrong-stream":
        source["parameters"]["source"]["streamIndex"] = 0
        message = "visible camera stream"
    elif failure == "crosses-cut":
        arguments["cues"] = [cue("camera-push", 22, 32)]
        message = "one exact visible source occurrence"
    elif failure == "range":
        trajectory["sourceRange"]["endTicks"] = 3100
        message = "selected face analysis range"
    else:
        (operation,) = compile_moves(**arguments)
        assert operation["outputRange"] == {"startFrame": 22, "endFrameExclusive": 30}
        assert operation["parameters"]["faceAnchor"] == camera["faceAnchor"]
        assert operation["parameters"]["sourceOccurrenceId"] == "visible"
        assert operation["parameters"]["behavior"]["nodes"][-1]["center"]["x"] > 0.5
        return
    with pytest.raises(CameraError, match=message):
        compile_moves(**arguments)


def test_existing_camera_uses_its_frozen_options_after_future_preferences_change():
    value = component()
    frozen = resolve_editing_craft_selection(invocation={"camera": {"enabled": True}})
    value["extensions"]["editingCraft"]["options"] = frozen
    operations = compile_moves(
        components=[value], selection=resolve_editing_craft_selection()
    )
    assert operations[0]["parameters"]["optionsHash"] == frozen["selectionHash"]
