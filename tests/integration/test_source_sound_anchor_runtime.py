"""Render a source-bound accent from originals, without granting listening approval."""

import shutil

import numpy as np
import pytest
from tests.integration import test_canonical_sound_proof_runtime as sound_runtime
from tests.integration.test_camera_proof_runtime import pixels
from tests.integration.test_ffmpeg_proof_executor import _pcm
from tests.integration.test_source_sound_anchor_flow import source_intent
from tests.test_proof_plan import regression_contract
from tests.test_timeline_animation_service import strategy

from avo.adapters.media.proof_executor import execute_ffmpeg_proof
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.capabilities import default_proof_capability_registry
from avo.timeline.animation import AnimationService
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import canonical_proof_media_inputs
from avo.timeline.proof_plan import ProofPlanCompiler

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
        reason="actual ffmpeg/ffprobe required",
    ),
]


def test_source_point_keeps_its_absolute_clock_in_full_and_window_exports(
    tmp_path, monkeypatch
):
    workspace = sound_runtime.recorded_program(tmp_path)
    cmap = workspace.store("cmap").load()["revisions"][-1]["snapshot"]

    def selected_intent(**kwargs):
        selected = source_intent(cmap)
        kwargs.pop("phase", None)
        selected.update(kwargs)
        return selected

    monkeypatch.setattr(sound_runtime, "intent", selected_intent)
    request = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=workspace.raw_dir / "edit" / "source-sound.mkv",
        frame_rate={"num": 24, "den": 1},
        width=128,
        height=72,
    )
    request["checkpoint"] = "motion-proof"
    request["output"].update(
        conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le"
    )
    compiler = ProofPlanCompiler(workspace, default_proof_capability_registry())
    renderer = TimelineRenderAdapter(proof_executor=execute_ffmpeg_proof)

    def render(name, window=None):
        plan = compiler.compile(request, regression_contract=regression_contract())
        report = compiler.preflight(
            plan,
            media_inputs=canonical_proof_media_inputs(workspace, plan),
            tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
        )
        assert report["status"] == "pass", report["blockers"]
        path = tmp_path / name
        renderer.render_proof_plan(plan, path, window=window)
        return path

    baseline = render("source-baseline.mkv")
    service, selected_request = sound_runtime.reviewed_sound(workspace, tmp_path)
    result = service.apply(selected_request)
    AnimationService(workspace).author(
        strategy(), actor="fixture", reason="Revalidate unchanged visual metadata"
    )
    mixed_output = render("source-selected.mkv")
    base, mixed = _pcm(baseline), _pcm(mixed_output)
    delta = mixed - base
    assert int(np.argmax(np.abs(delta[:, 0]))) == 12000
    assert 0.12 < np.max(np.abs(delta[:, 0])) < 0.13
    np.testing.assert_array_equal(
        pixels(baseline, 128, 72), pixels(mixed_output, 128, 72)
    )
    window = render("source-window.mkv", {"startFrame": 5, "endFrameExclusive": 19})
    np.testing.assert_allclose(_pcm(window), mixed[10000:38000], atol=3e-7)
    np.testing.assert_array_equal(
        pixels(window, 128, 72), pixels(mixed_output, 128, 72)[5:19]
    )
    assert result["acceptance"] == "pending-listening"
    assert workspace.store("cmap").load()["revisions"][-1]["snapshot"] == cmap
