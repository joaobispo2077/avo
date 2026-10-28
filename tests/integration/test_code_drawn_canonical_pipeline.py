"""Real raw picture/audio plus browser graphics through native canonical stores.

Store approvals below are explicit test decisions, not claims of human Watch QC.
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
from PIL import Image
from tests.integration.test_ffmpeg_proof_executor import _pcm
from tests.test_proof_plan import regression_contract
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_bmap_service import cue
from tests.test_timeline_cmap_service import snapshot, workspace
from tests.test_timeline_tracks_service import canonical_tracks

from avo import motion
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.adapters.motion.code_drawn import CodeDrawnAdapter, runtime_readiness
from avo.adapters.qc.code_drawn_review import CodeDrawnReviewProducer
from avo.adapters.qc.registry import CheckpointQcRegistry
from avo.timeline.animation import AnimationService
from avo.timeline.approval_service import native_proof_dependencies
from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.generated_assets import GeneratedAssetService
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import (
    canonical_proof_media_inputs,
    materialize_proof_plan,
    render_proof_microproofs,
)
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.review import validate_code_drawn_review
from avo.timeline.sync_service import SyncService
from avo.timeline.tracks import TracksService

pytestmark = pytest.mark.integration


def _pixels(path):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, np.uint8).reshape(-1, 96, 128, 4)


def _physical_cut(tmp_path):
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
            "testsrc2=s=128x96:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.1*sin(440*2*PI*t)|0.08*sin(660*2*PI*t):s=48000:d=2",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        capture_output=True,
        check=True,
    )
    sync = SyncService(ws)
    revision = sync.author_not_applicable(
        raw_fingerprints={"camera": file_fingerprint(source)["sha256"]},
        actor="test-fixture",
        reason="actual single muxed source",
    )
    evidence = sync.validate_current()
    sync.decide(
        decision="approved",
        candidate_hash=revision["contentHash"],
        evidence_bundle_hash=evidence["sha256"],
        actor="test-fixture",
        reason="test sync decision",
    )
    cut = snapshot(source, end=500)
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
    second = deepcopy(cut["segments"][0])
    second["segmentId"] = "segment-two"
    second["in"]["ticks"], second["out"]["ticks"] = 1000, 1500
    cut["segments"].append(second)
    revision = CMapService(ws).author(
        cut, actor="test-fixture", reason="two real raw-source intervals"
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
        conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le"
    )
    compiler = ProofPlanCompiler(ws)
    plan = compiler.compile(request, regression_contract=regression_contract())
    port = TimelineRenderAdapter().for_proof_plan(ws, plan)
    compiler.require_preflight(
        plan,
        media_inputs=canonical_proof_media_inputs(ws, plan),
        tool_readiness=port.proof_tool_readiness(plan),
    )
    port.render_proof_plan(plan, Path(plan["output"]["path"]), window=None)
    ws.store("cmap").approve(
        revision["revisionId"],
        revision_hash=revision["contentHash"],
        candidate_hash=file_fingerprint(Path(plan["output"]["path"]))["sha256"],
    )
    return ws, source, request


def _drawing(ws, source):
    instance = "canonical-overlay"
    directory = ws.raw_dir / "edit/derived/components" / instance
    motion.scaffold_code_drawn(
        directory,
        route="canvas",
        width=128,
        height=96,
        fps="30/1",
        frames=21,
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
    beat["kind"], beat["end"]["ticks"] = "animation", 800
    BMapService(ws).author(
        {"cues": [beat]}, actor="test-fixture", reason="drawing across the raw cut"
    )
    tracks = canonical_tracks(ws, source)
    for group in ("audioTracks", "videoTracks"):
        tracks[group]["layers"][0]["regions"] = [
            {"regionId": "program", "startTicks": 0, "endTicks": 1000, "cueIds": []}
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
                    "endTicks": 800,
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
        tracks, actor="test-fixture", reason="logical drawing layer"
    )
    animation = strategy()
    animation["framework"] = "code-drawn"
    animation["components"][0].pop("providerPatternRef")
    animation["components"][0]["extensions"] = {"codeDrawn": reference}
    AnimationService(ws).author(
        animation, actor="test-fixture", reason="inspectable source strategy"
    )
    output = ws.raw_dir / "edit/derived/overlay.mkv"
    motion.materialize_code_drawn(
        ws, instance, output=output, adapter=CodeDrawnAdapter()
    )
    record = json.loads(
        output.with_suffix(".generated-asset.json").read_text(encoding="utf-8")
    )
    return record


def test_real_canonical_drawing_has_exact_full_micro_pixels_and_original_pcm(tmp_path):
    if not runtime_readiness()["ready"] or not shutil.which("ffmpeg"):
        if os.environ.get("AVO_REQUIRE_CODE_DRAWN_RUNTIME") == "1":
            pytest.fail("Managed Chromium and FFmpeg required")
        pytest.skip("Managed Chromium and FFmpeg required")
    ws, source, request = _physical_cut(tmp_path)
    record = _drawing(ws, source)
    extension = record["parameters"]["codeDrawn"]
    request = deepcopy(request)
    request["checkpoint"] = "motion-proof"
    request["renderProfile"] = "master"
    request["validationPlan"]["microproof"] = [
        {"startFrame": 10, "endFrameExclusive": 20}
    ]
    request["output"]["path"] = str(ws.raw_dir / "edit/preview/full.mkv")
    request["videoGraph"]["operations"].append(
        {
            "operationId": "canonical-drawing",
            "kind": "overlay-video",
            "implementationId": "impl-overlay-video",
            "inputs": ["program-picture", "generated:" + record["assetId"]],
            "outputRange": {"startFrame": 3, "endFrameExclusive": 24},
            "parameters": {
                "generatedAssetRef": {
                    "assetId": record["assetId"],
                    "recordHash": record["recordHash"],
                    "locator": str(GeneratedAssetService(ws).path(record["assetId"])),
                },
                "inputLockRef": extension["inputLockRef"],
                "sourceFingerprint": record["output"],
                "sourceRange": {"startFrame": 0, "endFrameExclusive": 21},
                "placement": {"x": 0, "y": 0, "width": 128, "height": 96},
                "zOrder": 10,
                "layerRole": "overlay",
                "alphaMode": "straight",
            },
        }
    )
    before = ws.active_dependency_snapshot()
    compiler = ProofPlanCompiler(ws)
    plan = compiler.compile(request, regression_contract=regression_contract())
    assert all(
        "hyperframes" not in reference["adapterId"]
        for reference in plan["implementationRefs"]
    )
    # Public services receive raw ports and must configure admitted generated inputs.
    media_inputs = canonical_proof_media_inputs(ws, plan)
    gate = render_proof_microproofs(
        workspace=ws,
        proof_plan=plan,
        media_inputs=media_inputs,
        render_port=TimelineRenderAdapter(),
    )
    assert gate["status"] == "pass"
    assert all(item["status"] == "pass" for item in gate["results"])
    result = materialize_proof_plan(
        workspace=ws,
        proof_plan=plan,
        microproof_gate=gate["path"],
        media_inputs=media_inputs,
        render_port=TimelineRenderAdapter(),
    )
    full = Path(plan["output"]["path"])
    materialization = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert materialization == {
        key: value for key, value in result.items() if key != "path"
    }
    assert materialization["kind"] == "proof-plan"
    assert materialization["microproofGateHash"] == gate["gateHash"]
    assert materialization["output"] == file_fingerprint(full)
    full_pixels = _pixels(full)
    full_pcm = _pcm(full)
    for item in gate["results"]:
        bounds = item["window"]
        start, end = bounds["startFrame"], bounds["endFrameExclusive"]
        micro = Path(item["output"]["locator"])
        assert file_fingerprint(micro) == item["output"]
        assert np.array_equal(_pixels(micro), full_pixels[start:end])
        assert np.array_equal(_pcm(micro), full_pcm[start * 1600 : end * 1600])
    assert any(
        item["window"] == {"startFrame": 10, "endFrameExclusive": 20}
        for item in gate["results"]
    )
    assert np.array_equal(full_pcm, _pcm(ws.raw_dir / "edit/preview/cut.mkv"))
    assert not np.array_equal(
        full_pixels[3:24], _pixels(ws.raw_dir / "edit/preview/cut.mkv")[3:24]
    )
    drawing = next(
        item
        for item in plan["videoGraph"]["operations"]
        if item["operationId"] == "canonical-drawing"
    )
    assert drawing["parameters"]["inputLockRef"] == extension["inputLockRef"]
    assert ws.active_dependency_snapshot() == before

    producer = CodeDrawnReviewProducer()
    dependencies = native_proof_dependencies(materialization)
    source_receipt = ws.raw_dir / "edit/derived/overlay.generated-asset.json"
    package = motion.prepare_code_drawn_review(
        full,
        dependencies=dependencies,
        render_profile="master",
        candidate_contract=producer.probe_contract(full),
        source_receipts=[source_receipt],
        output_dir=ws.raw_dir / "edit/review/code-drawn-v001",
        producer=producer,
        sample_frames=[0, 3, 10, 15, 23, 29],
        transition_ranges=[{"startFrame": 13, "endFrameExclusive": 17}],
        loop_requested=False,
    )
    evidence = validate_code_drawn_review(
        package, candidate=full, dependencies=dependencies, render_profile="master"
    )
    assert package["state"] == "needs-human-judgment"
    assert package["approval"] is None
    assert package["findings"] == []
    assert len(package["sources"]) == 1
    assert package["sources"][0]["recordHash"] == record["recordHash"]
    assert package["candidateContract"] == {
        "width": 128,
        "height": 96,
        "frameRate": {"num": 30, "den": 1},
        "frameCount": 30,
    }
    assert evidence["status"] == "pending"
    assert evidence["coverage"]["decodedFrames"] == package["sampleFrames"]
    assert evidence["coverage"]["inspectedFrames"] == []
    assert evidence["coverage"]["reviewedWindows"] == 0
    assert evidence["coverage"]["reviewedSeconds"] == 0
    assert (
        evidence["reviewContext"]["codeDrawnReview"]["reviewHash"]
        == package["reviewHash"]
    )
    assert not any(item["kind"] == "loop-strip" for item in package["artifacts"])
    assert any(item["kind"] == "contact-sheet" for item in package["artifacts"])
    assert any(item["kind"] == "transition-strip" for item in package["artifacts"])
    for artifact in package["artifacts"]:
        if artifact["kind"] == "frame":
            with Image.open(artifact["path"]) as image:
                actual = np.asarray(image.convert("RGBA"))
            assert np.array_equal(actual, full_pixels[artifact["frame"]])
    assert ws.active_dependency_snapshot() == before

    # Exercise the actual final deterministic registry without claiming Watch,
    # transcript/listening, human disposition, or creator approval.
    registry = CheckpointQcRegistry()
    for checkpoint in ("pre-master", "deliver"):
        qc = registry.check(
            full,
            checkpoint=checkpoint,
            workspace=ws,
            dependencies=dependencies,
            materialization=materialization,
            materialization_path=Path(result["path"]),
        )
        evidence_by_kind = {item["kind"]: item for item in qc["evidence"]}
        for kind in ("lineage", "technical-qc", "source-fidelity"):
            assert evidence_by_kind[kind]["status"] == "pass", evidence_by_kind[kind]
        assert (
            evidence_by_kind["source-fidelity"]["details"]["nativeBasis"][
                "proofPlanHash"
            ]
            == plan["proofPlanHash"]
        )
    assert ws.active_dependency_snapshot() == before
