"""Physical FFmpeg graph tests; fixture generators do not replace code-drawn freshness."""

from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from tests.integration.test_ffmpeg_proof_executor import _execution, _nr_policy, _pcm

from avo.adapters.media.proof_executor import execute_ffmpeg_proof
from avo.capabilities import default_proof_capability_registry
from avo.timeline.contracts import (
    content_hash,
    document_hash_excluding,
    file_fingerprint,
)
from avo.timeline.generated_assets import GeneratedAssetService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
        reason="actual ffmpeg/ffprobe required",
    ),
]
FPS = Fraction(30000, 1001)
RATE = 48000


def _frames(path, width=640, height=360):
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
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, np.uint8).reshape(-1, height, width, 4)


def _encode_generated(path, *, opaque):
    width, height = (640, 360) if opaque else (40, 24)
    frames = np.zeros((60, height, width, 4), dtype=np.uint8)
    for frame in range(60):
        if opaque:
            frames[frame, :, :] = [20 + frame * 3, 180, 35, 255]
        else:
            frames[frame, 4:20, 4:36] = [180, 40, 210, 128]
            frames[frame, 8:16, 8:16] = [20 + frame * 3, 200, 35, 255]
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-s",
            f"{width}x{height}",
            "-r",
            "30000/1001",
            "-i",
            "-",
            "-an",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "bgra",
            str(path),
        ],
        input=frames.tobytes(),
        capture_output=True,
        check=True,
    )


def _generated(directory, service, *, asset_id, opaque):
    path = directory / f"{asset_id}.mkv"
    _encode_generated(path, opaque=opaque)
    lock = {"instanceId": asset_id, "generator": "fixture.ffmpeg", "seed": 7}
    lock["inputLockHash"] = content_hash(lock)
    lock_path = directory / f"{asset_id}.input-lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    record = service.register(
        {
            "assetId": asset_id,
            "role": "authored-graphic" if opaque else "overlay",
            "generator": {
                "adapterId": "fixture.ffmpeg",
                "version": "1",
                "executableSha256": file_fingerprint(Path(shutil.which("ffmpeg")))[
                    "sha256"
                ],
            },
            "parameters": {
                "instanceId": asset_id,
                "inputLockHash": lock["inputLockHash"],
            },
            "inputs": [
                {
                    "artifactId": "fixture-input-lock",
                    "fingerprint": file_fingerprint(lock_path),
                    "ancestryRole": "dependency",
                }
            ],
            "sourceFree": True,
            "environment": {
                "platform": "test",
                "dependencies": {"encoder": "actual-ffmpeg"},
            },
            "output": file_fingerprint(path),
            "reproducibility": "verified",
            "approvalReference": None,
        }
    )
    service.admit(asset_id)
    return {
        "path": path,
        "record": record,
        "receipt": service.path(asset_id),
        "lock": lock,
        "lock_path": lock_path,
        "opaque": opaque,
    }


@pytest.fixture(scope="module")
def graph_assets(tmp_path_factory):
    directory = tmp_path_factory.mktemp("generated-executor")
    execution = _execution(directory)
    service = GeneratedAssetService(
        SimpleNamespace(timeline_dir=directory / "edit/timeline")
    )
    return {
        "execution": execution,
        "opaque": _generated(
            directory, service, asset_id="fixture-opaque", opaque=True
        ),
        "alpha": _generated(directory, service, asset_id="fixture-alpha", opaque=False),
    }


def _conformance(execution):
    value = deepcopy(execution)
    value["output"].update(conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le")
    return value


def _add_generated(
    execution,
    asset,
    *,
    kind,
    start,
    end,
    local_start=7,
    operation_id="generated-layer",
    z_order=10,
    role="overlay",
):
    record = asset["record"]
    capability = default_proof_capability_registry().resolve(kind)
    assert capability is not None, f"Missing native capability {kind}"
    reference = capability.proof_reference()
    if reference not in execution["implementationRefs"]:
        execution["implementationRefs"].append(reference)
    execution["canonicalInputLock"][f"generated:{record['assetId']}"] = record[
        "recordHash"
    ]
    execution["canonicalInputLock"][f"input-lock:{record['assetId']}"] = asset["lock"][
        "inputLockHash"
    ]
    parameters = {
        "generatedAssetRef": {
            "assetId": record["assetId"],
            "recordHash": record["recordHash"],
            "locator": str(asset["receipt"]),
        },
        "inputLockRef": {
            "path": str(asset["lock_path"]),
            "sha256": file_fingerprint(asset["lock_path"])["sha256"],
        },
        "sourceFingerprint": deepcopy(record["output"]),
        "sourceRange": {
            "startFrame": local_start,
            "endFrameExclusive": local_start + end - start,
        },
    }
    if kind == "overlay-video":
        parameters.update(
            placement={"x": 120, "y": 70, "width": 40, "height": 24},
            zOrder=z_order,
            layerRole=role,
            alphaMode="straight",
        )
    operation = {
        "operationId": operation_id,
        "kind": kind,
        "implementationId": reference["implementationId"],
        "inputs": (["program-picture"] if kind == "overlay-video" else [])
        + [f"generated:{record['assetId']}"],
        "outputRange": {"startFrame": start, "endFrameExclusive": end},
        "parameters": parameters,
    }
    if kind == "generated-clip":
        execution["videoGraph"]["operations"][0] = operation
    else:
        execution["videoGraph"]["operations"].append(operation)
    return operation


def test_explicit_lossless_conformance_uses_the_existing_audio_graph(
    graph_assets, tmp_path
):
    execution = _conformance(graph_assets["execution"])
    output = tmp_path / "conformance.mkv"
    original = deepcopy(execution)
    result = execute_ffmpeg_proof(execution, output)
    streams = {stream["codec_type"]: stream for stream in result["media"]["streams"]}
    assert streams["video"]["codec_name"] == "ffv1"
    assert streams["audio"]["codec_name"] == "pcm_s32le"
    assert _frames(output).shape[0] == 60
    assert len(_pcm(output)) == 96096
    assert result["audioEncodeCount"] == 1
    assert execution == original


def test_generated_full_frame_replaces_picture_only_and_preserves_audio(
    graph_assets, tmp_path
):
    base = _conformance(graph_assets["execution"])
    baseline = tmp_path / "base.mkv"
    execute_ffmpeg_proof(base, baseline)
    generated = deepcopy(base)
    _add_generated(
        generated, graph_assets["opaque"], kind="generated-clip", start=0, end=30
    )
    output = tmp_path / "generated.mkv"
    execute_ffmpeg_proof(generated, output)
    picture = _frames(output)
    source = _frames(graph_assets["opaque"]["path"])
    for program_frame in (0, 12, 29):
        assert (
            np.max(
                np.abs(
                    picture[program_frame, 100, 100, :3].astype(int)
                    - source[program_frame + 7, 100, 100, :3]
                )
            )
            <= 2
        )
    assert np.array_equal(picture[30:], _frames(baseline)[30:])
    assert np.array_equal(_pcm(output), _pcm(baseline))


@pytest.mark.parametrize("noise_reduction", [False, True])
def test_cut_spanning_alpha_has_exact_full_micro_phase_and_unchanged_audio(
    graph_assets, tmp_path, noise_reduction
):
    execution = _conformance(graph_assets["execution"])
    if noise_reduction:
        execution["audioGraph"]["operations"][0]["parameters"][
            "dialogueNoiseReductionPolicy"
        ] = _nr_policy()
    baseline = tmp_path / "base.mkv"
    execute_ffmpeg_proof(execution, baseline)
    _add_generated(
        execution, graph_assets["alpha"], kind="overlay-video", start=10, end=50
    )
    frozen = deepcopy(execution)
    full = tmp_path / "full.mkv"
    full_result = execute_ffmpeg_proof(execution, full)
    assert bool(full_result["sourceDialogueNoisePolicies"]) is noise_reduction
    execution["window"] = {"startFrame": 20, "endFrameExclusive": 40}
    micro = tmp_path / "micro.mkv"
    execute_ffmpeg_proof(execution, micro)
    pictures = _frames(full)
    assert np.array_equal(_frames(micro), pictures[20:40])
    begin = round(Fraction(20, 1) / FPS * RATE)
    end = round(Fraction(40, 1) / FPS * RATE)
    assert np.array_equal(_pcm(micro), _pcm(full)[begin:end])
    assert np.array_equal(_pcm(full), _pcm(baseline))
    baseline_frames = _frames(baseline)
    assert np.array_equal(pictures[:10], baseline_frames[:10])
    assert np.array_equal(pictures[50:], baseline_frames[50:])
    assert np.array_equal(pictures[:, :70], baseline_frames[:, :70])
    asset_frames = _frames(graph_assets["alpha"]["path"], width=40, height=24)
    for frame in (10, 29, 30, 49):
        expected = asset_frames[7 + frame - 10, 11, 11, :3].astype(int)
        assert np.max(np.abs(pictures[frame, 81, 131, :3].astype(int) - expected)) <= 2
    execution["window"] = None
    assert execution == frozen


def test_overlay_order_is_frozen_and_caption_layer_remains_above_graphics(
    graph_assets, tmp_path
):
    execution = _conformance(graph_assets["execution"])
    _add_generated(
        execution,
        graph_assets["alpha"],
        kind="overlay-video",
        start=10,
        end=40,
        local_start=1,
        operation_id="graphic",
        z_order=10,
    )
    _add_generated(
        execution,
        graph_assets["alpha"],
        kind="overlay-video",
        start=10,
        end=40,
        local_start=20,
        operation_id="caption",
        z_order=20,
        role="caption",
    )
    first = tmp_path / "order-a.mkv"
    execute_ffmpeg_proof(execution, first)
    execution["videoGraph"]["operations"][-2:] = reversed(
        execution["videoGraph"]["operations"][-2:]
    )
    second = tmp_path / "order-b.mkv"
    execute_ffmpeg_proof(execution, second)
    assert np.array_equal(_frames(first), _frames(second))
    expected = _frames(graph_assets["alpha"]["path"], width=40, height=24)[
        20, 11, 11, :3
    ].astype(int)
    assert np.max(np.abs(_frames(first)[10, 81, 131, :3].astype(int) - expected)) <= 2


@pytest.mark.parametrize(
    "fault",
    [
        "implementation",
        "source-range",
        "source-eof",
        "source-fingerprint",
        "asset-lock",
        "input-lock",
        "unknown-operation",
    ],
)
def test_generated_contract_mismatch_fails_before_output(graph_assets, tmp_path, fault):
    execution = _conformance(graph_assets["execution"])
    operation = _add_generated(
        execution, graph_assets["alpha"], kind="overlay-video", start=10, end=50
    )
    if fault == "implementation":
        operation["implementationId"] = "impl-trim"
    elif fault == "source-range":
        operation["parameters"]["sourceRange"]["endFrameExclusive"] -= 1
    elif fault == "source-eof":
        operation["parameters"]["sourceRange"] = {
            "startFrame": 55,
            "endFrameExclusive": 95,
        }
    elif fault == "source-fingerprint":
        operation["parameters"]["sourceFingerprint"]["sha256"] = "f" * 64
    elif fault == "asset-lock":
        execution["canonicalInputLock"]["generated:fixture-alpha"] = "f" * 64
    elif fault == "input-lock":
        operation["parameters"]["inputLockRef"]["sha256"] = "f" * 64
    else:
        operation["kind"] = "unregistered-drawing"
    output = tmp_path / "must-not-exist.mkv"
    with pytest.raises(RuntimeError):
        execute_ffmpeg_proof(execution, output)
    assert not output.exists()


def test_transparent_generated_asset_cannot_be_used_as_an_opaque_base(
    graph_assets, tmp_path
):
    execution = _conformance(graph_assets["execution"])
    _add_generated(
        execution, graph_assets["alpha"], kind="generated-clip", start=0, end=30
    )
    output = tmp_path / "invalid-base.mkv"
    with pytest.raises(RuntimeError, match="opaque|alpha|dimension"):
        execute_ffmpeg_proof(execution, output)
    assert not output.exists()


@pytest.mark.parametrize("operation", ["duck", "mix", "crossfade"])
def test_unimplemented_music_sfx_graph_fails_instead_of_dropping_mix(
    graph_assets, tmp_path, operation
):
    execution = _conformance(graph_assets["execution"])
    execution["audioGraph"]["operations"].append(
        {
            "operationId": "music-or-sfx-treatment",
            "kind": operation,
            "range": {"startSample": 0, "endSampleExclusive": 96096},
            "parameters": {
                "nodeId": "music-bed",
                "preserve": ["dialogue", "music", "sfx"],
            },
        }
    )
    output = tmp_path / "unsupported-mix.mkv"
    with pytest.raises(RuntimeError, match="audio|duck|mix|crossfade"):
        execute_ffmpeg_proof(execution, output)
    assert not output.exists()


@pytest.mark.parametrize("bad", [False, 1, "true"])
def test_lossless_codec_selection_requires_explicit_boolean_conformance(
    graph_assets, tmp_path, bad
):
    execution = _conformance(graph_assets["execution"])
    execution["output"]["conformance"] = bad
    output = tmp_path / "invalid-conformance.mkv"
    with pytest.raises(RuntimeError):
        execute_ffmpeg_proof(execution, output)
    assert not output.exists()


def _frozen_plan(execution, output):
    value = deepcopy(execution)
    value["canonicalInputLock"].update(
        {
            key: content_hash({"fixture-canonical": key})
            for key in ("cmap", "bmap", "tracks", "animation", "sync-map")
        }
    )
    plan = {
        "schemaVersion": "1.0.0",
        "proofPlanId": "fixture-generated-plan",
        "iterationId": "fixture-iteration",
        "canonicalInputLock": value["canonicalInputLock"],
        "regressionContract": {
            "contractId": "fixture-contract",
            "ledgerHash": content_hash("ledger"),
            "iterationId": "fixture-iteration",
            "obligations": [],
            "historicalRiskWindows": [],
            "conflicts": [],
            "contractHash": content_hash("contract"),
        },
        "renderProfile": "motion-proof",
        "output": {**value["output"], "path": str(output)},
        "capabilityResolution": [
            {
                "operationId": operation["operationId"],
                "capability": operation["kind"],
                "implementationId": operation["implementationId"],
                "status": "resolved",
            }
            for operation in value["videoGraph"]["operations"]
        ],
        "implementationRefs": value["implementationRefs"],
        "videoGraph": value["videoGraph"],
        "audioGraph": value["audioGraph"],
        "events": [],
        "validationPlan": {
            "preflight": [],
            "microproof": [],
            "fullReview": [],
            "historicalRegression": [],
        },
        "visionReviewPlanRef": None,
        "lineagePolicy": {
            "allowedMediaClasses": ["source", "generated-asset"],
            "prohibitedMediaClasses": [
                "proof",
                "preview",
                "proxy",
                "master",
                "delivery",
            ],
            "recursive": True,
        },
        "producer": {
            "name": "physical-test",
            "version": "1",
            "compiler": "frozen-fixture",
        },
    }
    plan["proofPlanHash"] = document_hash_excluding(plan, "proofPlanHash")
    return plan


def test_default_adapter_executes_the_immutable_generated_graph(graph_assets, tmp_path):
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    execution = _conformance(graph_assets["execution"])
    _add_generated(
        execution, graph_assets["alpha"], kind="overlay-video", start=10, end=50
    )
    output = tmp_path / "adapter.mkv"
    plan = _frozen_plan(execution, output)
    frozen = deepcopy(plan)
    result = TimelineRenderAdapter().render_proof_plan(
        plan,
        output,
        window={"startFrame": 20, "endFrameExclusive": 40},
    )
    assert result["status"] == "pass"
    assert result["proofPlanHash"] == plan["proofPlanHash"]
    assert result["graphHash"]
    assert result["output"]["sha256"] == file_fingerprint(output)["sha256"]
    assert len(_frames(output)) == 20
    assert plan == frozen


def test_generated_picture_split_preserves_full_dialogue_nr_and_fade_envelope(
    graph_assets, tmp_path
):
    execution = _conformance(graph_assets["execution"])
    execution["audioGraph"]["operations"][0]["parameters"][
        "dialogueNoiseReductionPolicy"
    ] = _nr_policy()
    baseline = tmp_path / "continuous-audio.mkv"
    execute_ffmpeg_proof(execution, baseline)
    original_base = deepcopy(execution["videoGraph"]["operations"])
    left = deepcopy(original_base[0])
    left["operationId"] = "left-original"
    left["outputRange"]["endFrameExclusive"] = 15
    left["parameters"]["sourceRange"] = {
        "startTicks": 0,
        "endTicks": 15,
        "timebase": {"num": 1001, "den": 30000},
    }
    generated = _add_generated(
        execution,
        graph_assets["opaque"],
        kind="generated-clip",
        start=15,
        end=30,
    )
    execution["videoGraph"]["operations"] = [left, generated, original_base[1]]
    full = tmp_path / "split-picture.mkv"
    result = execute_ffmpeg_proof(execution, full)
    assert result["sourceDialogueNoisePolicies"]
    assert np.array_equal(_pcm(full), _pcm(baseline))
    execution["window"] = {"startFrame": 10, "endFrameExclusive": 35}
    micro = tmp_path / "split-window.mkv"
    execute_ffmpeg_proof(execution, micro)
    assert np.array_equal(_frames(micro), _frames(full)[10:35])
    start = round(Fraction(10, 1) / FPS * RATE)
    end = round(Fraction(35, 1) / FPS * RATE)
    assert np.array_equal(_pcm(micro), _pcm(full)[start:end])


@pytest.mark.parametrize("z_order", [5, 10])
def test_frozen_caption_order_cannot_hide_accessibility_layer(
    graph_assets, tmp_path, z_order
):
    execution = _conformance(graph_assets["execution"])
    _add_generated(
        execution,
        graph_assets["alpha"],
        kind="overlay-video",
        start=10,
        end=40,
        operation_id="graphic",
        z_order=10,
    )
    _add_generated(
        execution,
        graph_assets["alpha"],
        kind="overlay-video",
        start=10,
        end=40,
        operation_id="caption",
        z_order=z_order,
        role="caption",
    )
    output = tmp_path / "hidden-caption.mkv"
    with pytest.raises(RuntimeError, match="caption"):
        execute_ffmpeg_proof(execution, output)
    assert not output.exists()


def test_dependency_mutation_before_publication_cannot_publish_a_proof(
    graph_assets, tmp_path
):
    service = GeneratedAssetService(
        SimpleNamespace(timeline_dir=tmp_path / "edit/timeline")
    )
    asset = _generated(tmp_path, service, asset_id="race-alpha", opaque=False)
    execution = _conformance(graph_assets["execution"])
    _add_generated(execution, asset, kind="overlay-video", start=10, end=50)
    calls = []

    def admission(reference, input_lock, canonical_lock):
        calls.append(reference)
        if len(calls) == 2:
            asset["lock_path"].write_text("changed while encoding", encoding="utf-8")
        return deepcopy(asset["record"])

    output = tmp_path / "must-not-publish.mkv"
    with pytest.raises(RuntimeError, match="changed|mismatch"):
        execute_ffmpeg_proof(execution, output, generated_asset_validator=admission)
    assert len(calls) == 2
    assert not output.exists()
