"""Actual canonical camera-node sound timing, without claiming human listening QC."""

import shutil
import subprocess
from copy import deepcopy

import numpy as np
import pytest
from tests.editing_craft_fixtures import labeled_video
from tests.integration import test_canonical_sound_proof_runtime as sound_runtime
from tests.integration.test_camera_proof_runtime import pixels
from tests.integration.test_ffmpeg_proof_executor import _pcm
from tests.test_camera_evaluator import geometry
from tests.test_proof_plan import regression_contract
from tests.test_sound_opportunities import intent
from tests.test_timeline_animation_service import strategy

from avo.adapters.media.proof_executor import execute_ffmpeg_proof
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.capabilities import default_proof_capability_registry
from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.animation import AnimationService
from avo.timeline.bmap_service import BMapService
from avo.timeline.camera import make_camera_treatment
from avo.timeline.contracts import file_fingerprint
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import canonical_proof_media_inputs
from avo.timeline.motion_review import MotionReviewService
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.tracks import TracksService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
        reason="actual ffmpeg/ffprobe required",
    ),
]


def original_recording(path):
    picture = labeled_video(
        path.with_name("labeled-original.mkv"), size=(128, 72), bit_depth=16
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(picture),
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.1*sin(440*2*PI*t)|0:s=48000:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-map",
            "0:v",
            "-map",
            "2:a",
            "-map",
            "1:a",
            "-map",
            "2:a",
            "-t",
            "1",
            "-c:v",
            "copy",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def install_camera(workspace):
    cue = deepcopy(
        workspace.store("bmap").load()["revisions"][-1]["snapshot"]["cues"][0]
    )
    cue.update(
        kind="animation",
        targetLayerId="base-video",
        contentRef={"itemId": "mo04", "componentId": "camera-node"},
    )
    BMapService(workspace).author(
        {"cues": [cue]}, actor="fixture", reason="Camera interval"
    )
    tracks = deepcopy(workspace.store("tracks").load()["revisions"][-1]["snapshot"])
    TracksService(workspace).author(tracks, actor="fixture", reason="Retain microphone")
    selected = resolve_editing_craft_selection(invocation={"camera": {"enabled": True}})
    wrapper = make_camera_treatment(
        "punch-settle",
        target_layer_id="base-video",
        source_id="camera",
        source_sha256=file_fingerprint(workspace.raw_dir / "camera.mkv")["sha256"],
        geometry=geometry(
            codedWidth=128,
            codedHeight=72,
            baselineCrop={"x": 0, "y": 0, "width": 128, "height": 72},
        ),
        options=selected,
    )
    animation = strategy()
    animation["strategyContractVersion"] = "2.0.0"
    component = animation["components"][0]
    component["componentId"] = "camera-node"
    component["extensions"] = {"editingCraft": wrapper}
    AnimationService(workspace).author(
        animation, actor="fixture", reason="Selected camera"
    )
    return animation


def test_camera_peak_and_selected_sfx_keep_the_same_absolute_clock_in_full_and_window(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sound_runtime, "_recording", original_recording)
    workspace = sound_runtime.recorded_program(tmp_path)
    animation = install_camera(workspace)
    item = next(
        value
        for value in MotionReviewService(workspace).project()["items"]
        if value.get("componentRef") == "camera-node"
    )
    anchor = {
        "componentId": "camera-node",
        "pathHash": item["camera"]["pathHash"],
        "sourceSha256": item["camera"]["sourceSha256"],
        "nodeIndex": 1,
    }

    def camera_intent(**kwargs):
        value = intent(**kwargs, kind="camera-emphasis", cameraAnchor=anchor)
        value.pop("phase")
        return value

    monkeypatch.setattr(sound_runtime, "intent", camera_intent)
    request = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=workspace.raw_dir / "edit" / "camera-sound.mkv",
        frame_rate={"num": 24, "den": 1},
        width=128,
        height=72,
    )
    request["checkpoint"] = "motion-proof"
    request["output"].update(
        conformance=True,
        videoCodec="ffv1",
        audioCodec="pcm_s32le",
        pixelFormat="gbrp16le",
    )
    compiler = ProofPlanCompiler(workspace, default_proof_capability_registry())
    renderer = TimelineRenderAdapter(proof_executor=execute_ffmpeg_proof)

    def render(name, window=None):
        plan = compiler.compile(request, regression_contract=regression_contract())
        preflight = compiler.preflight(
            plan,
            media_inputs=canonical_proof_media_inputs(workspace, plan),
            tool_readiness=renderer.proof_tool_readiness(plan),
        )
        assert preflight["status"] == "pass", preflight["blockers"]
        path = tmp_path / name
        renderer.render_proof_plan(plan, path, window=window)
        return plan, path

    _, baseline = render("camera-without-sfx.mkv")
    service, choice = sound_runtime.reviewed_sound(workspace, tmp_path)
    choice["contexts"][0].update(role="main-scene", syntheticEffectApproved=True)
    applied = service.apply(choice)
    AnimationService(workspace).author(
        animation, actor="fixture", reason="Current tracks"
    )
    plan, output = render("camera-with-sfx.mkv")
    fit = applied["receipt"]["choices"][0]["fit"]
    # Cue100..900ms is frames2..21; peak0.25 maps to frame7, sample14000.
    assert fit["opportunity"]["programFrame"] == 7
    assert fit["opportunity"]["cameraAnchor"] == anchor
    assert fit["event"]["resolvedImpactSample"] == 14000
    assert (
        len([node for node in plan["audioGraph"]["nodes"] if node["kind"] == "sfx"])
        == 1
    )
    assert (
        len(
            [
                op
                for op in plan["videoGraph"]["operations"]
                if op["kind"] == "camera-transform"
            ]
        )
        == 1
    )
    base, mixed = _pcm(baseline), _pcm(output)
    delta = mixed - base
    assert int(np.argmax(np.abs(delta[:, 0]))) == 14000
    assert 0.12 < np.max(np.abs(delta[:, 0])) < 0.13
    assert 0.06 < np.max(np.abs(delta[:, 1])) < 0.065
    np.testing.assert_array_equal(pixels(baseline, 128, 72), pixels(output, 128, 72))
    assert not np.array_equal(
        pixels(output, 128, 72)[7],
        pixels(workspace.raw_dir / "camera.mkv", 128, 72)[7],
    )
    _, window = render(
        "camera-sound-window.mkv", {"startFrame": 5, "endFrameExclusive": 19}
    )
    np.testing.assert_allclose(_pcm(window), mixed[10000:38000], atol=3e-7)
    np.testing.assert_array_equal(
        pixels(window, 128, 72), pixels(output, 128, 72)[5:19]
    )
    assert applied["acceptance"] == "pending-listening"
    np.testing.assert_allclose(_pcm(window), mixed[10000:38000], atol=3e-7)
    np.testing.assert_array_equal(
        pixels(window, 128, 72), pixels(output, 128, 72)[5:19]
    )
    assert applied["acceptance"] == "pending-listening"
