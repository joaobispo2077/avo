"""Real code-drawn alpha through original-picture Shorts and its independent audio.

Test fixture approvals are explicit test decisions, not human visual approval.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from tests.integration.test_code_drawn_canonical_pipeline import _pixels
from tests.integration.test_ffmpeg_proof_executor import _pcm
from tests.test_proof_plan import regression_contract
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_bmap_service import cue
from tests.test_timeline_cmap_service import snapshot, workspace
from tests.test_timeline_tracks_service import canonical_tracks

from avo import motion, shorts, shorts_contract, shorts_fidelity, shorts_media
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.adapters.motion.code_drawn import CodeDrawnAdapter, runtime_readiness
from avo.timeline.animation import AnimationService
from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.generated_assets import GeneratedAssetService
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import canonical_proof_media_inputs
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.sync_service import SyncService
from avo.timeline.tracks import TracksService

pytestmark = pytest.mark.integration


def _original_ten_bit_cut(tmp_path):
    ws = workspace(tmp_path)
    source = ws.raw_dir / "camera.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=128x96:r=30:d=2,format=yuv420p10le",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.1*sin(440*2*PI*t)|0.08*sin(660*2*PI*t):s=48000:d=2",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "yuv420p10le",
            "-colorspace",
            "bt709",
            "-color_trc",
            "bt709",
            "-color_primaries",
            "bt709",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    sync = SyncService(ws)
    revision = sync.author_not_applicable(
        raw_fingerprints={"camera": file_fingerprint(source)["sha256"]},
        actor="test-fixture",
        reason="actual single muxed original",
    )
    evidence = sync.validate_current()
    sync.decide(
        decision="approved",
        candidate_hash=revision["contentHash"],
        evidence_bundle_hash=evidence["sha256"],
        actor="test-fixture",
        reason="fixture sync decision",
    )
    cut = snapshot(source, end=2000)
    cut["sources"][0]["streamMetadata"] = {
        "videoStreamIndex": 0,
        "audioSelection": {
            "streamIndex": 1,
            "sourceSampleRate": 48000,
            "sourceLayout": "stereo",
            "channels": [0, 1],
            "outputLayout": "stereo",
        },
    }
    revision = CMapService(ws).author(
        cut, actor="test-fixture", reason="genuine 10-bit original interval"
    )
    request = initial_cut_proof_request(
        ws,
        iteration_id="iteration-0001",
        output=ws.raw_dir / "edit/preview/cut.mkv",
        frame_rate={"num": 30, "den": 1},
        width=128,
        height=96,
    )
    request["output"].update(
        conformance=True,
        videoCodec="ffv1",
        audioCodec="pcm_s32le",
    )
    compiler = ProofPlanCompiler(ws)
    plan = compiler.compile(request, regression_contract=regression_contract())
    port = TimelineRenderAdapter().for_proof_plan(ws, plan)
    compiler.require_preflight(
        plan,
        media_inputs=canonical_proof_media_inputs(ws, plan),
        tool_readiness=port.proof_tool_readiness(plan),
    )
    candidate = Path(plan["output"]["path"])
    port.render_proof_plan(plan, candidate, window=None)
    ws.store("cmap").approve(
        revision["revisionId"],
        revision_hash=revision["contentHash"],
        candidate_hash=file_fingerprint(candidate)["sha256"],
    )
    return ws, source


def _bound_alpha(ws, source):
    instance = "shorts-overlay"
    directory = ws.raw_dir / "edit/derived/components" / instance
    motion.scaffold_code_drawn(
        directory,
        route="canvas",
        width=128,
        height=96,
        fps="30/1",
        frames=36,
        background="transparent",
    )
    composition = directory / "composition.json"
    reference = {
        "instanceId": instance,
        "manifestRef": {
            "path": composition.relative_to(ws.raw_dir).as_posix(),
            "sha256": file_fingerprint(composition)["sha256"],
        },
    }
    beat = cue()
    beat["kind"], beat["end"]["ticks"] = "animation", 1300
    BMapService(ws).author(
        {"cues": [beat]}, actor="test-fixture", reason="1.2 second drawing interval"
    )
    tracks = canonical_tracks(ws, source)
    for group in ("audioTracks", "videoTracks"):
        tracks[group]["layers"][0]["regions"] = [
            {"regionId": "program", "startTicks": 0, "endTicks": 2000, "cueIds": []}
        ]
    tracks["videoTracks"]["layers"].append(
        {
            "layerId": "graphic",
            "order": 1,
            "role": "overlay",
            "generatedSourceRef": {"engine": "code-drawn", **reference},
            "regions": [
                {
                    "regionId": "drawing",
                    "startTicks": 100,
                    "endTicks": 1300,
                    "cueIds": ["cue-one"],
                }
            ],
            "placement": {"x": 0, "y": 0, "width": 128, "height": 96},
            "zOrder": 10,
            "safeZones": ["face", "captions"],
            "faceAvoidance": True,
        }
    )
    TracksService(ws).author(
        tracks, actor="test-fixture", reason="full-canvas logical drawing"
    )
    animation = strategy()
    animation["framework"] = "code-drawn"
    animation["components"][0].pop("providerPatternRef")
    animation["components"][0]["extensions"] = {"codeDrawn": reference}
    AnimationService(ws).author(
        animation, actor="test-fixture", reason="inspectable native drawing"
    )
    output = ws.raw_dir / "edit/derived/shorts-alpha.mkv"
    motion.materialize_code_drawn(
        ws, instance, output=output, adapter=CodeDrawnAdapter()
    )
    record = json.loads(
        output.with_suffix(".generated-asset.json").read_text(encoding="utf-8")
    )
    return reference, record


def _prepared_voice(ws, source):
    path = ws.raw_dir / "edit/derived/prepared-dialogue.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-af",
            "atrim=start_sample=4800:end_sample=62400,asetpts=N/SR/TB",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s24le",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    assert np.array_equal(_pcm(path), _pcm(source)[4800:62400])
    return {
        "path": str(path),
        "hash": file_fingerprint(path)["sha256"],
        "durationSec": 1.2,
        "muted": False,
    }


def _require_runtime():
    if (
        runtime_readiness()["ready"]
        and shutil.which("ffmpeg")
        and shutil.which("ffprobe")
    ):
        return
    if os.environ.get("AVO_REQUIRE_CODE_DRAWN_RUNTIME") == "1":
        pytest.fail(
            "Managed Chromium and FFmpeg are required for real Shorts acceptance"
        )
    pytest.skip("Managed Chromium and FFmpeg are required for real Shorts acceptance")


def test_real_native_shorts_alpha_preserves_original_audio_clock_and_picture_contract(
    tmp_path, monkeypatch
):
    _require_runtime()
    ws, source = _original_ten_bit_cut(tmp_path)
    reference, receipt = _bound_alpha(ws, source)
    voice = _prepared_voice(ws, source)
    extension = receipt["parameters"]["codeDrawn"]
    item = {
        "id": "01",
        "layout": {"mode": "full-frame"},
        "sourceSegments": [
            {
                "startSec": 0.1,
                "endSec": 1.3,
                "sourceFingerprint": file_fingerprint(source)["sha256"],
            }
        ],
        "inputFingerprint": shorts_contract.content_hash("physical-native-short"),
        "speed": 1,
        "editedDurationSec": 1.2,
    }
    spec = {
        "motionEngine": "code-drawn",
        "codeDrawn": {
            **deepcopy(reference),
            "inputLockRef": deepcopy(extension["inputLockRef"]),
            "generatedAssetRef": {
                "assetId": receipt["assetId"],
                "recordHash": receipt["recordHash"],
                "locator": str(GeneratedAssetService(ws).path(receipt["assetId"])),
            },
        },
        "assets": {"dialogueAudio": voice},
        "captions": [],
    }
    output = {
        "width": 128,
        "height": 96,
        "fps": 30,
        "frameRateRational": "30/1",
        "audioChannels": 2,
    }
    work = ws.raw_dir / "edit/shorts/proof-attempt"
    work.mkdir(parents=True)
    final = work / "native-short.mp4"

    def forbidden(*args, **kwargs):
        pytest.fail("The real code-drawn Shorts path invoked HyperFrames")

    monkeypatch.setattr(shorts, "compile_project", forbidden)
    monkeypatch.setattr(shorts, "_check_hyperframes_project", forbidden)
    before = ws.active_dependency_snapshot()
    admitted = shorts._render_source_fidelity(
        {"planHash": shorts_contract.content_hash("physical-short-plan")},
        item,
        source,
        output,
        spec,
        work,
        final,
        None,
        workspace=ws,
    )
    report = json.loads((work / "source-fidelity.json").read_text(encoding="utf-8"))
    assert admitted["recordHash"] == receipt["recordHash"]
    assert _pixels(final).shape == (36, 96, 128, 4)
    assert report["video"]["pix_fmt"] == "yuv420p10le"
    assert report["video"]["r_frame_rate"] == "30/1"
    assert report["microproofGate"]["status"] == "passed"
    assert "code-drawn" in report["microproofGate"]["graphicsReview"]
    assert "pending" in report["microproofGate"]["graphicsReview"]
    lock = report["canonicalInputLock"]
    assert lock["source"] == file_fingerprint(source)["sha256"]
    assert lock["generated:" + receipt["assetId"]] == receipt["recordHash"]
    assert lock["input-lock:" + reference["instanceId"]] == extension["inputLockHash"]
    assert not any("hyperframes" in key for key in lock)
    mixed = Path(report["audioMix"]["path"])
    assert _pcm(mixed).shape == (57600, 2)
    original = _pcm(source)[4800:62400]
    normalized = _pcm(mixed)
    for channel in range(2):
        correlations = []
        for lag in range(-8, 9):
            a, b = (
                (original[-lag:, channel], normalized[:lag, channel])
                if lag < 0
                else (
                    original[: len(original) - lag or None, channel],
                    normalized[lag:, channel],
                )
            )
            correlations.append(
                float(np.dot(a, b) / np.sqrt(np.dot(a, a) * np.dot(b, b)))
            )
        assert int(np.argmax(correlations)) == 8
        assert correlations[8] > 0.999
    baseline = work / "without-graphics.mp4"
    shorts_fidelity.render_fidelity(
        source,
        baseline,
        source_segments=item["sourceSegments"],
        source_sha256=lock["source"],
        canonical_lock=lock,
        width=128,
        height=96,
        fps="30/1",
        speed=1,
        mixed_audio_path=mixed,
        mixed_audio_sha256=report["audioMix"]["sha256"],
        preset="slow",
    )
    assert np.array_equal(_pcm(final), _pcm(baseline))
    assert not np.array_equal(_pixels(final), _pixels(baseline))
    probe = shorts_media.probe_media(final)
    audio = next(
        stream for stream in probe["streams"] if stream["codec_type"] == "audio"
    )
    assert (audio["codec_name"], audio["sample_rate"], audio["channels"]) == (
        "aac",
        "48000",
        2,
    )
    assert abs(float(audio["duration"]) - 1.2) <= 1 / 48000
    assert abs(float(audio["start_time"])) <= 1 / 48000
    assert ws.active_dependency_snapshot() == before
