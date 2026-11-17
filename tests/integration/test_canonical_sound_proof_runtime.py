"""Real canonical sound publication/export; review and creator decisions are fixtures."""

import shutil
from copy import deepcopy

import numpy as np
import pytest
from tests.editing_craft_fixtures import channel_impulses
from tests.integration.test_camera_proof_runtime import pixels
from tests.integration.test_cmap_cut_review_runtime import _review
from tests.integration.test_ffmpeg_proof_executor import _pcm, _recording
from tests.test_proof_plan import regression_contract
from tests.test_sfx_catalog import annotate, scan
from tests.test_sound_application import repropose
from tests.test_sound_opportunities import intent
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_bmap_service import cue
from tests.test_timeline_cmap_service import snapshot, workspace
from tests.test_timeline_tracks_service import canonical_tracks

from avo.adapters.media.proof_executor import execute_ffmpeg_proof
from avo.adapters.media.sfx_analysis import SfxAnalyzer
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.adapters.registry import build_sound_source_probe
from avo.capabilities import default_proof_capability_registry
from avo.editing_craft import resolve_editing_craft_selection
from avo.sfx_catalog import SfxCatalogService
from avo.timeline.animation import AnimationService
from avo.timeline.approval_service import ApprovalService
from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import canonical_proof_media_inputs, materialize_cut_proof
from avo.timeline.motion_review import MotionReviewService
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.sound_planning import SoundPlanningService
from avo.timeline.tracks import TracksService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
        reason="actual ffmpeg/ffprobe required",
    ),
]


def recorded_program(tmp_path):
    ws = workspace(tmp_path)
    original = ws.raw_dir / "camera.mkv"
    _recording(original)
    cut = snapshot(original)
    cut["sources"][0]["streamMetadata"] = {
        "videoStreamIndex": 0,
        "audioSelection": {
            "streamIndex": 2,
            "channels": [0],
            "sourceLayout": "stereo",
            "outputLayout": "dual-mono",
            "sourceSampleRate": 48000,
        },
    }
    revision = CMapService(ws).author(cut, actor="fixture", reason="Original recording")
    materialized = materialize_cut_proof(
        workspace=ws,
        cmap_revision_id=revision["revisionId"],
        output_path=ws.raw_dir / "edit" / "cut.mp4",
    )
    review = _review(ws, revision, materialized)
    ApprovalService(ws).decide(
        decision="approved",
        revision_id=revision["revisionId"],
        review_path=review["reviewPath"],
        materialization_path=ws.timeline_dir
        / "materializations"
        / "cut-proof"
        / f"{materialized['materializationId']}.json",
        actor="fixture",
        reason="Synthetic gate fixture, not actual creator acceptance",
    )
    visual = cue()
    visual["contentRef"]["itemId"] = "mo04"
    visual["end"]["ticks"] = 900
    BMapService(ws).author({"cues": [visual]}, actor="fixture", reason="Visible accent")
    tracks = canonical_tracks(ws, original)
    for key in ("audioTracks", "videoTracks"):
        tracks[key]["layers"][0]["regions"][0]["endTicks"] = 900
    tracks["audioTracks"]["layers"][0]["channels"] = [0]
    TracksService(ws).author(tracks, actor="fixture", reason="Selected microphone")
    AnimationService(ws).author(strategy(), actor="fixture", reason="Motion metadata")
    return ws


def reviewed_sound(ws, tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    channel_impulses(library / "impact.wav")
    catalogue = SfxCatalogService(ws, roots={"test": library}, analyzer=SfxAnalyzer())
    generation = scan(catalogue)
    generation = annotate(
        catalogue,
        generation["generationId"],
        generation["entries"][0]["entryId"],
        {
            "rights": {
                "status": "licensed",
                "license": "generated-test-fixture",
                "evidenceRef": "synthetic-fixture",
            },
            "marker": {"sample": 12000, "reviewerRef": "known-synthetic-impulse"},
        },
    )
    service = SoundPlanningService(
        ws, catalogue=catalogue, source_probe=build_sound_source_probe()
    )
    proposal = service.propose(
        {
            "contractVersion": "1.0.0",
            "operation": "propose",
            "operationId": "recorded-sound",
            "actor": "fixture",
            "reason": "One audible accent",
            "expectedBasis": MotionReviewService(ws).project()["basisHeads"],
            "expectedGeneration": generation["generationId"],
            "selection": resolve_editing_craft_selection(
                invocation={"soundMatching": {"enabled": True}}
            ),
            "clock": {
                "frameRate": {"num": 24, "den": 1},
                "sampleRate": 48000,
                "programEndFrame": 24,
            },
            "intents": [intent()],
        }
    )
    return service, {
        "contractVersion": "1.0.0",
        "operation": "apply",
        "operationId": "recorded-sound-apply",
        "actor": "fixture",
        "reason": "Audition the exact native marker",
        "proposalHash": proposal["proposalRef"]["sha256"],
        "expectedBasis": proposal["proposal"]["basisHeads"],
        "expectedGeneration": generation["generationId"],
        "choices": [
            {
                "eventId": proposal["proposal"]["opportunities"][0]["eventId"],
                "entryId": generation["entries"][0]["entryId"],
                "trimRange": {"startSample": 0, "endSampleExclusive": 36000},
                "mix": {
                    "sourceLayout": "stereo",
                    "targetLayout": "stereo",
                    "channelMap": [0, 1],
                    "gainDb": -12,
                    "peakCeilingDbfs": -3,
                    "fadeInSamples": 0,
                    "fadeOutSamples": 0,
                    "ducking": None,
                },
            }
        ],
        "contexts": [
            {
                "cueId": "cue-one",
                "role": "authored-graphic",
                "orderedEventIds": [],
                "syntheticEffectApproved": False,
            }
        ],
    }


def test_published_sound_reaches_the_normal_export_once_and_follows_real_dialogue(
    tmp_path,
):
    ws = recorded_program(tmp_path)
    request = initial_cut_proof_request(
        ws,
        iteration_id="iteration-0001",
        output=ws.raw_dir / "edit" / "normal.mkv",
        frame_rate={"num": 24, "den": 1},
        width=128,
        height=72,
    )
    request["checkpoint"] = "motion-proof"
    request["output"].update(
        conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le"
    )
    original_request = deepcopy(request)
    compiler = ProofPlanCompiler(ws, default_proof_capability_registry())
    renderer = TimelineRenderAdapter(proof_executor=execute_ffmpeg_proof)

    def render(value, name, window=None):
        plan = compiler.compile(value, regression_contract=regression_contract())
        report = compiler.preflight(
            plan,
            media_inputs=canonical_proof_media_inputs(ws, plan),
            tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
        )
        assert report["status"] == "pass", report["blockers"]
        path = tmp_path / name
        renderer.render_proof_plan(plan, path, window=window)
        return plan, path

    _, baseline = render(request, "baseline.mkv")
    service, selected = reviewed_sound(ws, tmp_path)
    applied = service.apply(selected)
    AnimationService(ws).author(strategy(), actor="fixture", reason="Current metadata")
    plan, output = render(request, "selected.mkv")
    assert applied["acceptance"] == "pending-listening"
    assert (
        len([node for node in plan["audioGraph"]["nodes"] if node["kind"] == "sfx"])
        == 1
    )
    base, mixed = _pcm(baseline), _pcm(output)
    assert len(base) == len(mixed) == 48000
    assert np.sqrt(np.mean(base**2)) > 0.05
    delta = mixed - base
    fit = applied["receipt"]["choices"][0]["fit"]
    marker = fit["event"]["resolvedImpactSample"]
    assert int(np.argmax(np.abs(delta[:, 0]))) == marker
    assert 0.12 < np.max(np.abs(delta[:, 0])) < 0.13
    assert 0.06 < np.max(np.abs(delta[:, 1])) < 0.065
    np.testing.assert_array_equal(pixels(baseline, 128, 72), pixels(output, 128, 72))
    _, micro = render(request, "window.mkv", {"startFrame": 5, "endFrameExclusive": 19})
    np.testing.assert_allclose(_pcm(micro), mixed[10000:38000], atol=3e-7)

    ducked = repropose(service, selected, identity="recorded-duck")
    ducked["choices"][0]["mix"]["ducking"] = {
        "sidechainLayerId": "dialogue",
        "amountDb": 8,
        "attackMs": 20,
        "releaseMs": 250,
    }
    service.apply(ducked)
    AnimationService(ws).author(strategy(), actor="fixture", reason="Current metadata")
    _, quiet_path = render(request, "ducked.mkv")
    quiet = _pcm(quiet_path)
    assert abs((quiet - base)[marker, 0]) < abs(delta[marker, 0]) * 0.9
    np.testing.assert_allclose(quiet[:12000], base[:12000], atol=3e-7)
    assert request == original_request
