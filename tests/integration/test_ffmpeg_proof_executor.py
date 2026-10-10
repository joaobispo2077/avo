"""Actual encoded media verifies routing, fades and the shared window graph."""

from __future__ import annotations

import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from avo.adapters.media.proof_executor import _tail_policy, execute_ffmpeg_proof
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.capabilities import default_proof_capability_registry
from avo.timeline.contracts import document_hash_excluding, file_fingerprint

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="actual ffmpeg/ffprobe required",
)


def _recording(path: Path, *, external: bool = False, rate: int = 48000) -> None:
    color = "blue" if external else "red"
    audio = (
        f"aevalsrc=0.1*sin(880*2*PI*t)|0.1*sin(1320*2*PI*t):s={rate}:d=2"
        if external
        else "aevalsrc=0.1*sin(440*2*PI*t)|0:s=48000:d=2"
    )
    argv = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        f"color={color}:s=128x72:r=30000/1001:d=2",
        "-f",
        "lavfi",
        "-i",
        audio,
    ]
    if external:
        argv += ["-map", "0:v", "-map", "1:a"]
    else:
        argv += [
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
        ]
    subprocess.run(
        argv + ["-t", "2", "-c:v", "ffv1", "-c:a", "pcm_s16le", str(path)],
        check=True,
        capture_output=True,
    )


def _execution(tmp_path: Path) -> dict:
    sources = [tmp_path / "raw.mkv", tmp_path / "external.mkv"]
    for index, path in enumerate(sources):
        _recording(path, external=bool(index))
    execution = {
        "output": {
            "width": 640,
            "height": 360,
            "frameRate": {"num": 30000, "den": 1001},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "videoCodec": "libx264",
            "audioCodec": "aac",
        },
        "videoGraph": {"operations": []},
        "audioGraph": {
            "sampleRate": 48000,
            "nodes": [],
            "operations": [],
            "singleFinalEncode": True,
        },
        "canonicalInputLock": {},
        "implementationRefs": [
            default_proof_capability_registry().resolve("trim").proof_reference()
        ],
        "events": [],
        "window": None,
    }
    for i, path in enumerate(sources):
        source_id = f"source-{i}"
        source = {
            "locator": str(path),
            "sha256": file_fingerprint(path)["sha256"],
            "mediaClass": "source",
        }
        execution["canonicalInputLock"][f"source:{source_id}"] = source["sha256"]
        execution["videoGraph"]["operations"].append(
            {
                "operationId": f"trim-{i}",
                "kind": "trim",
                "implementationId": "impl-trim",
                "inputs": [source_id],
                "outputRange": {
                    "startFrame": i * 30,
                    "endFrameExclusive": (i + 1) * 30,
                },
                "parameters": {
                    "sourceId": source_id,
                    "source": {**source, "streamIndex": 0},
                    "sourceRange": {
                        "startTicks": 0,
                        "endTicks": 1001,
                        "timebase": {"num": 1, "den": 1000},
                    },
                },
            }
        )
        region = {"startSample": i * 48048, "endSampleExclusive": (i + 1) * 48048}
        execution["audioGraph"]["nodes"].append(
            {
                "nodeId": f"audio-{i}",
                "kind": "source",
                "sourceSampleRate": 48000,
                "targetSampleRate": 48000,
                "sourceLayout": "stereo",
                "targetLayout": "stereo",
                "channelMap": [0, 1] if i else [0, 0],
                "latencyCompensationSamples": 0,
                "sourceRange": {"startSample": 0, "endSampleExclusive": 48048},
                "outputRange": region,
            }
        )
        execution["audioGraph"]["operations"].append(
            {
                "operationId": f"audio-trim-{i}",
                "kind": "trim",
                "range": region,
                "parameters": {
                    "nodeId": f"audio-{i}",
                    "sourceId": source_id,
                    "source": {**source, "streamIndex": 1 if i else 2},
                    "fadeInSamples": 1440,
                    "fadeOutSamples": 1440,
                },
            }
        )
    execution["audioGraph"]["operations"].append(
        {
            "operationId": "final-encode",
            "kind": "encode",
            "range": {"startSample": 0, "endSampleExclusive": 96096},
            "parameters": {},
        }
    )
    return execution


def _pcm(path: Path) -> np.ndarray:
    data = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-f", "f32le", "-"],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(data, np.float32).reshape(-1, 2)


def test_explicit_bounded_video_tail_preserves_audio_and_exact_frames(tmp_path):
    execution = _execution(tmp_path)
    source = tmp_path / "short-picture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=128x72:r=30:d=0.866666667",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.2*sin(880*2*PI*t)|0.2*sin(1320*2*PI*t):s=48000:d=1.001",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    execution["videoGraph"]["operations"] = execution["videoGraph"]["operations"][:1]
    execution["audioGraph"]["nodes"] = execution["audioGraph"]["nodes"][:1]
    execution["audioGraph"]["nodes"][0]["channelMap"] = [0, 1]
    execution["audioGraph"]["operations"] = [
        execution["audioGraph"]["operations"][0],
        execution["audioGraph"]["operations"][-1],
    ]
    execution["audioGraph"]["operations"][-1]["range"]["endSampleExclusive"] = 48048
    fingerprint = file_fingerprint(source)
    execution["canonicalInputLock"]["source:source-0"] = fingerprint["sha256"]
    video = execution["videoGraph"]["operations"][0]["parameters"]
    audio = execution["audioGraph"]["operations"][0]["parameters"]
    video["source"].update(locator=str(source), sha256=fingerprint["sha256"])
    audio["source"].update(
        locator=str(source), sha256=fingerprint["sha256"], streamIndex=1
    )
    with pytest.raises(RuntimeError, match="exact frame contract"):
        execute_ffmpeg_proof(execution, tmp_path / "untagged.mp4")
    assert not (tmp_path / "untagged.mp4").exists()
    video["videoTailPolicy"] = {"mode": "hold-last-frame", "maxHoldMilliseconds": 200}
    output = tmp_path / "held.mp4"
    result = execute_ffmpeg_proof(execution, output)
    stream = next(s for s in result["media"]["streams"] if s["codec_type"] == "video")
    assert stream["nb_frames"] == "30"
    assert result["audioEncodeCount"] == 1
    assert 100 < result["sourceVideoTailPolicies"][0]["actualHoldMilliseconds"] < 200
    assert result["sourceVideoTailPolicies"][0]["sourceId"] == "source-0"
    assert np.sqrt(np.mean(_pcm(output)[44000:45500] ** 2)) > 0.1
    execution["window"] = {"startFrame": 25, "endFrameExclusive": 30}
    micro = execute_ffmpeg_proof(execution, tmp_path / "tail-micro.mp4")
    assert (
        next(s for s in micro["media"]["streams"] if s["codec_type"] == "video")[
            "nb_frames"
        ]
        == "5"
    )
    video["videoTailPolicy"]["maxHoldMilliseconds"] = 50
    with pytest.raises(RuntimeError, match="video tail hold exceeds"):
        execute_ffmpeg_proof(execution, tmp_path / "overbudget.mp4")
    assert not (tmp_path / "overbudget.mp4").exists()


@pytest.mark.parametrize(
    "policy",
    [
        None,
        [],
        {},
        {"mode": "hold-last-frame", "maxHoldMilliseconds": True},
        {"mode": "hold-last-frame", "maxHoldMilliseconds": 0},
        {"mode": "hold-last-frame", "maxHoldMilliseconds": 201},
        {"mode": "hold-last-frame", "maxHoldMilliseconds": 1.5},
        {"mode": "loop", "maxHoldMilliseconds": 200},
        {"mode": "hold-last-frame", "maxHoldMilliseconds": 200, "ignored": True},
    ],
)
def test_video_tail_policy_rejects_unbounded_or_ignored_contract(policy):
    with pytest.raises(RuntimeError):
        _tail_policy(policy)


def test_real_proof_routes_embedded_mic_and_external_stereo_with_fades(tmp_path):
    execution = _execution(tmp_path)
    original = deepcopy(execution)
    output = tmp_path / "full.mp4"
    result = execute_ffmpeg_proof(execution, output)
    assert result["audioEncodeCount"] == 1
    video = next(s for s in result["media"]["streams"] if s["codec_type"] == "video")
    assert (
        video["width"],
        video["height"],
        video["r_frame_rate"],
        video["nb_frames"],
    ) == (640, 360, "30000/1001", "60")
    audio = _pcm(output)
    assert np.sqrt(np.mean(audio[12000:24000, 0] ** 2)) > 0.05
    assert np.max(np.abs(audio[12000:24000, 0] - audio[12000:24000, 1])) < 0.001
    assert np.sqrt(np.mean((audio[60000:72000, 0] - audio[60000:72000, 1]) ** 2)) > 0.07
    assert np.sqrt(np.mean(audio[47808:48048] ** 2)) < 0.025
    execution["window"] = {"startFrame": 15, "endFrameExclusive": 45}
    micro = execute_ffmpeg_proof(execution, tmp_path / "micro.mp4")
    microvideo = next(
        s for s in micro["media"]["streams"] if s["codec_type"] == "video"
    )
    assert microvideo["nb_frames"] == "30"
    cropped = _pcm(tmp_path / "micro.mp4")
    assert np.sqrt(np.mean(cropped[12000:14000] ** 2)) > 0.05
    assert np.sqrt(np.mean(cropped[23800:24024] ** 2)) < 0.025
    execution["window"] = None
    assert execution == original


def test_default_adapter_executes_schema_valid_immutable_plan(tmp_path):
    execution = _execution(tmp_path)
    output = tmp_path / "adapter.mp4"
    execution["canonicalInputLock"].update(
        {key: "a" * 64 for key in ("cmap", "bmap", "tracks", "animation", "sync-map")}
    )
    plan = {
        "schemaVersion": "1.0.0",
        "proofPlanId": "proof-plan-test",
        "iterationId": "iteration-test",
        "canonicalInputLock": execution["canonicalInputLock"],
        "regressionContract": {
            "contractId": "contract-test",
            "ledgerHash": "a" * 64,
            "iterationId": "iteration-test",
            "obligations": [],
            "historicalRiskWindows": [],
            "conflicts": [],
            "contractHash": "b" * 64,
        },
        "renderProfile": "cut-proof",
        "output": {**execution["output"], "path": str(output)},
        "capabilityResolution": [],
        "implementationRefs": execution["implementationRefs"],
        "videoGraph": execution["videoGraph"],
        "audioGraph": execution["audioGraph"],
        "events": [],
        "validationPlan": {
            "preflight": [],
            "microproof": [],
            "fullReview": [],
            "historicalRegression": [],
        },
        "visionReviewPlanRef": None,
        "lineagePolicy": {
            "allowedMediaClasses": ["source"],
            "prohibitedMediaClasses": [
                "proof",
                "preview",
                "proxy",
                "master",
                "delivery",
            ],
            "recursive": True,
        },
        "producer": {"name": "test", "version": "1", "compiler": "fixture"},
        "proofPlanHash": "",
    }
    plan["proofPlanHash"] = document_hash_excluding(plan, "proofPlanHash")
    result = TimelineRenderAdapter().render_proof_plan(
        plan, output, window={"startFrame": 15, "endFrameExclusive": 45}
    )
    assert result["proofPlanHash"] == plan["proofPlanHash"]
    assert result["graphHash"]
    assert result["output"]["sha256"] == file_fingerprint(output)["sha256"]


def test_native_44100_insert_requires_explicit_resample_preserving_stereo(tmp_path):
    execution = _execution(tmp_path)
    external = tmp_path / "external-44100.mkv"
    _recording(external, external=True, rate=44100)
    digest = file_fingerprint(external)["sha256"]
    execution["canonicalInputLock"]["source:source-1"] = digest
    picture = execution["videoGraph"]["operations"][1]["parameters"]["source"]
    audio_source = execution["audioGraph"]["operations"][1]["parameters"]["source"]
    for source in (picture, audio_source):
        source.update(locator=str(external), sha256=digest)
    node = execution["audioGraph"]["nodes"][1]
    node["sourceSampleRate"] = 44100
    node["sourceRange"]["endSampleExclusive"] = 44144
    with pytest.raises(RuntimeError, match="explicit resample"):
        execute_ffmpeg_proof(execution, tmp_path / "missing-resample.mp4")
    execution["audioGraph"]["operations"].append(
        {
            "operationId": "resample-external",
            "kind": "resample",
            "range": node["outputRange"],
            "parameters": {
                "nodeId": node["nodeId"],
                "sourceSampleRate": 44100,
                "targetSampleRate": 48000,
            },
        }
    )
    output = tmp_path / "resampled.mp4"
    result = execute_ffmpeg_proof(execution, output)
    metadata = next(s for s in result["media"]["streams"] if s["codec_type"] == "audio")
    assert (metadata["sample_rate"], metadata["channels"]) == ("48000", 2)
    audio = _pcm(output)[60000:72000]
    assert np.sqrt(np.mean((audio[:, 0] - audio[:, 1]) ** 2)) > 0.07
    for channel, expected in enumerate((880, 1320)):
        spectrum = np.abs(np.fft.rfft(audio[:, channel]))
        frequency = np.argmax(spectrum) * 48000 / len(audio)
        assert abs(frequency - expected) < 5


def test_many_single_frame_segments_keep_exact_contiguous_audio_duration(tmp_path):
    execution = _execution(tmp_path)
    execution["output"]["frameRate"] = {"num": 60, "den": 1}
    picture = execution["videoGraph"]["operations"][0]
    node = execution["audioGraph"]["nodes"][0]
    audio_trim = execution["audioGraph"]["operations"][0]
    execution["videoGraph"]["operations"] = []
    execution["audioGraph"]["nodes"] = []
    execution["audioGraph"]["operations"] = []
    for index in range(12):
        video = deepcopy(picture)
        video["operationId"] = f"trim-short-{index}"
        video["outputRange"] = {"startFrame": index, "endFrameExclusive": index + 1}
        video["parameters"]["sourceRange"]["endTicks"] = 17
        execution["videoGraph"]["operations"].append(video)
        audio = deepcopy(node)
        audio["nodeId"] = f"audio-short-{index}"
        audio["sourceRange"]["endSampleExclusive"] = 800
        audio["outputRange"] = {
            "startSample": index * 800,
            "endSampleExclusive": (index + 1) * 800,
        }
        execution["audioGraph"]["nodes"].append(audio)
        trim = deepcopy(audio_trim)
        trim["operationId"] = f"audio-trim-short-{index}"
        trim["range"] = audio["outputRange"]
        trim["parameters"].update(
            nodeId=audio["nodeId"], fadeInSamples=0, fadeOutSamples=0
        )
        execution["audioGraph"]["operations"].append(trim)
    execution["audioGraph"]["operations"].append(
        {
            "operationId": "final-encode",
            "kind": "encode",
            "range": {"startSample": 0, "endSampleExclusive": 9600},
            "parameters": {},
        }
    )
    result = execute_ffmpeg_proof(execution, tmp_path / "short-segments.mp4")
    audio = next(s for s in result["media"]["streams"] if s["codec_type"] == "audio")
    assert audio["time_base"] == "1/48000"
    assert abs(audio["duration_ts"] - 9600) <= 1


@pytest.mark.parametrize(
    "fault",
    [
        "ignored-operation",
        "source-changed",
        "event",
        "audio-stream",
        "audio-layout",
        "ancestry",
    ],
)
def test_executor_fails_before_output_for_unsupported_or_changed_graph(tmp_path, fault):
    execution = _execution(tmp_path)
    if fault == "ignored-operation":
        execution["audioGraph"]["operations"].append({"kind": "duck"})
    elif fault == "event":
        execution["events"] = [{"role": "caption"}]
    elif fault == "audio-stream":
        execution["audioGraph"]["operations"][0]["parameters"]["source"][
            "streamIndex"
        ] = 0
    elif fault == "audio-layout":
        execution["audioGraph"]["nodes"][0]["sourceLayout"] = "mono"
    elif fault == "ancestry":
        execution["videoGraph"]["operations"][0]["parameters"]["source"]["ancestry"] = [
            {"parent": {"mediaClass": "proof", "locator": "old.mp4"}}
        ]
    else:
        (tmp_path / "raw.mkv").write_bytes(b"changed")
    with pytest.raises(RuntimeError):
        execute_ffmpeg_proof(execution, tmp_path / "bad.mp4")
    assert not (tmp_path / "bad.mp4").exists()


def _nr_policy(strength=50):
    return {
        "mode": "afftdn",
        "role": "presenter-dialogue",
        "strengthPercent": strength,
        "streamIndex": 2,
        "channelIndex": 0,
        "approvedByUser": True,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"strengthPercent": True},
        {"mode": "other"},
        {"role": "game"},
        {"streamIndex": 1},
        {"channelIndex": 1},
        {"unknown": 1},
    ],
)
def test_native_nr_rejects_unsupported_before_output(tmp_path, change):
    execution = _execution(tmp_path)
    value = _nr_policy()
    value.update(change)
    execution["audioGraph"]["operations"][0]["parameters"][
        "dialogueNoiseReductionPolicy"
    ] = value
    output = tmp_path / "rejected.mp4"
    with pytest.raises(ValueError):
        execute_ffmpeg_proof(execution, output)
    assert not output.exists()


def test_native_nr_preserves_selected_voice_timing_stereo_and_sample_count(tmp_path):
    execution = _execution(tmp_path)
    source = tmp_path / "noisy-original.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=128x72:r=30000/1001:d=2",
            "-f",
            "lavfi",
            "-i",
            r"aevalsrc=0.1*sin(2*PI*(440*t+120*t*t))*(0.7+0.3*sin(13*2*PI*t))*(between(t\,0.15\,0.75)+between(t\,0.95\,1.0)):s=48000:d=2",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=white:amplitude=0.002:sample_rate=48000:duration=2:seed=42",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-filter_complex",
            "[1:a][2:a]amix=inputs=2:normalize=0,pan=stereo|c0=c0|c1=0*c0[mic]",
            "-map",
            "0:v",
            "-map",
            "3:a",
            "-map",
            "[mic]",
            "-map",
            "3:a",
            "-t",
            "2",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    digest = file_fingerprint(source)["sha256"]
    execution["canonicalInputLock"]["source:source-0"] = digest
    for source_spec in [
        execution["videoGraph"]["operations"][0]["parameters"]["source"],
        execution["audioGraph"]["operations"][0]["parameters"]["source"],
    ]:
        source_spec.update(locator=str(source), sha256=digest)
    baseline = tmp_path / "raw-proof.mp4"
    execute_ffmpeg_proof(execution, baseline)
    execution["audioGraph"]["operations"][0]["parameters"][
        "dialogueNoiseReductionPolicy"
    ] = _nr_policy()
    output = tmp_path / "nr-proof.mp4"
    record = execute_ffmpeg_proof(execution, output)
    raw = _pcm(baseline)
    treated = _pcm(output)
    assert len(raw) == len(treated)
    voiced = slice(12000, 30000)
    noise = slice(40000, 44000)
    assert (
        np.sqrt(np.mean(treated[noise, 0] ** 2))
        < np.sqrt(np.mean(raw[noise, 0] ** 2)) * 0.8
    )
    assert (
        np.sqrt(np.mean(treated[voiced, 0] ** 2))
        > np.sqrt(np.mean(raw[voiced, 0] ** 2)) * 0.5
    )
    correlation = np.fft.irfft(
        np.fft.rfft(treated[:48048, 0], 131072)
        * np.conj(np.fft.rfft(raw[:48048, 0], 131072)),
        131072,
    )
    lag = int(np.argmax(correlation))
    assert min(lag, 131072 - lag) <= 2
    assert (
        np.sqrt(np.mean((treated[voiced, 0] - treated[voiced, 1]) ** 2))
        < np.sqrt(np.mean(treated[voiced, 0] ** 2)) * 0.005
    )
    # The one AAC encoder's reservoir can change with preceding dialogue.
    # The unprocessed stereo insert remains within 2% encoded PCM error.
    assert (
        np.sqrt(np.mean((treated[50000:90000] - raw[50000:90000]) ** 2))
        < np.sqrt(np.mean(raw[50000:90000] ** 2)) * 0.02
    )
    assert record["sourceDialogueNoisePolicies"][0]["sourceId"] == "source-0"
    assert (
        record["sourceDialogueNoisePolicies"][0]["filter"]
        == "afftdn=nr=12.00:nf=-32.0:tn=1"
    )
    assert record["audioEncodeCount"] == 1
    tail = slice(45600, 46560)
    assert (
        np.sqrt(np.mean(treated[tail, 0] ** 2))
        > np.sqrt(np.mean(raw[tail, 0] ** 2)) * 0.5
    )
    execution["window"] = {"startFrame": 15, "endFrameExclusive": 30}
    window = tmp_path / "nr-window.mp4"
    execute_ffmpeg_proof(execution, window)
    fragment = _pcm(window)
    expected = treated[24024:48048]
    assert (
        np.sqrt(np.mean((fragment[:22000] - expected[:22000]) ** 2))
        < np.sqrt(np.mean(expected[:22000] ** 2)) * 0.03
    )


def test_valid_one_frame_nr_with_bounded_fades_preserves_signal_and_duration(tmp_path):
    execution = _execution(tmp_path)
    execution["output"]["frameRate"] = {"num": 60, "den": 1}
    execution["videoGraph"]["operations"] = execution["videoGraph"]["operations"][:1]
    execution["videoGraph"]["operations"][0]["outputRange"] = {
        "startFrame": 0,
        "endFrameExclusive": 1,
    }
    execution["videoGraph"]["operations"][0]["parameters"]["sourceRange"][
        "endTicks"
    ] = 20
    node = execution["audioGraph"]["nodes"][0]
    node["sourceRange"]["endSampleExclusive"] = 960
    node["outputRange"] = {"startSample": 0, "endSampleExclusive": 800}
    execution["audioGraph"]["nodes"] = [node]
    trim = execution["audioGraph"]["operations"][0]
    trim["range"] = node["outputRange"]
    trim["parameters"].update(
        fadeInSamples=400, fadeOutSamples=400, dialogueNoiseReductionPolicy=_nr_policy()
    )
    encode = execution["audioGraph"]["operations"][-1]
    encode["range"] = node["outputRange"]
    execution["audioGraph"]["operations"] = [trim, encode]
    output = tmp_path / "one-frame.mp4"
    record = execute_ffmpeg_proof(execution, output)
    samples = _pcm(output)
    assert np.max(np.abs(samples[:800])) > 0.001
    assert record["media"]["streams"][0]["nb_frames"] == "1"
    assert record["audioEncodeCount"] == 1
    execution["window"] = {"startFrame": 0, "endFrameExclusive": 1}
    micro = tmp_path / "one-frame-window.mp4"
    execute_ffmpeg_proof(execution, micro)
    np.testing.assert_array_equal(_pcm(micro), samples)
