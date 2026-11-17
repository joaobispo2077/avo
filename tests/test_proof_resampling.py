"""Explicit resampling covers decoded dialogue, music, effects and ambience."""

import shutil
import wave
from contextlib import nullcontext
from copy import deepcopy

import numpy as np
import pytest

from avo.adapters.media.proof_executor import _validate_resampling, execute_ffmpeg_proof
from avo.timeline.contracts import file_fingerprint
from avo.timeline.proof_validation_stage import proof_validation_batch

ROLES = ("source", "music", "sfx", "ambience")


def _declarations():
    nodes, operations = [], []
    for index, role in enumerate(ROLES):
        source_rate = (44100, 96000, 96000, 32000)[index]
        node = {
            "nodeId": role,
            "kind": role,
            "sourceSampleRate": source_rate,
            "targetSampleRate": 48000,
            "outputRange": {"startSample": 0, "endSampleExclusive": 4800},
        }
        nodes.append(node)
        operations.append(
            {
                "operationId": "resample-" + role,
                "kind": "resample",
                "range": deepcopy(node["outputRange"]),
                "parameters": {
                    "nodeId": role,
                    "sourceSampleRate": source_rate,
                    "targetSampleRate": 48000,
                },
            }
        )
    return {"nodes": nodes, "operations": operations}


def test_mixed_decoded_roles_accept_exact_explicit_rate_conversions():
    graph = _declarations()
    _validate_resampling(graph, graph["nodes"], 48000)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "range", "source-rate", "target-rate", "unneeded"]
)
def test_each_role_preserves_strict_resample_contracts(role, fault):
    graph = _declarations()
    index = ROLES.index(role)
    operation = graph["operations"][index]
    if fault == "missing":
        graph["operations"].pop(index)
    elif fault == "duplicate":
        graph["operations"].append(deepcopy(operation))
    elif fault == "range":
        operation["range"]["endSampleExclusive"] += 1
    elif fault == "source-rate":
        operation["parameters"]["sourceSampleRate"] += 1
    elif fault == "target-rate":
        operation["parameters"]["targetSampleRate"] = 44100
    else:
        graph["nodes"][index]["sourceSampleRate"] = 48000
        operation["parameters"]["sourceSampleRate"] = 48000
    with pytest.raises(RuntimeError, match="resample|Resample"):
        _validate_resampling(graph, graph["nodes"], 48000)


@pytest.mark.parametrize("role", ROLES)
def test_matching_rate_needs_no_resample_declaration(role):
    node = {
        "nodeId": role,
        "kind": role,
        "sourceSampleRate": 48000,
        "targetSampleRate": 48000,
    }
    _validate_resampling({"operations": []}, [node], 48000)


@pytest.mark.parametrize("fault", ["unknown-parameter", "orphan", "silence"])
def test_unused_or_unknown_resample_declarations_still_fail(fault):
    graph = _declarations()
    if fault == "unknown-parameter":
        graph["operations"][0]["parameters"]["filter"] = "arbitrary"
    elif fault == "orphan":
        graph["operations"][0]["parameters"]["nodeId"] = "undeclared"
    else:
        graph["nodes"][0]["kind"] = "silence"
    with pytest.raises(RuntimeError, match="resample"):
        _validate_resampling(graph, graph["nodes"], 48000)


@pytest.mark.integration
@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Actual FFmpeg/FFprobe required",
)
@pytest.mark.parametrize(
    ("role", "batch"),
    [("music", False), ("sfx", False), ("ambience", False), ("sfx", True)],
)
def test_native_placed_96k_mix_preserves_voice_stereo_and_microproof_clock(
    tmp_path, role, batch
):
    from tests.integration.test_otio_placed_render_runtime import _decoded, _execution

    execution, _ = _execution(tmp_path)
    baseline = tmp_path / "baseline.mkv"
    execute_ffmpeg_proof(execution, baseline)
    source = tmp_path / "native-96k.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(96000)
        output.writeframes(
            np.tile(np.array([2000, 4000], dtype="<i2"), (96000, 1)).tobytes()
        )
    fingerprint = file_fingerprint(source)
    graph = execution["audioGraph"]
    output_range = {"startSample": 60000, "endSampleExclusive": 84000}
    source_range = {"startSample": 0, "endSampleExclusive": 48000}
    node = {
        "nodeId": "native-mix",
        "kind": role,
        "sourceSampleRate": 96000,
        "targetSampleRate": 48000,
        "sourceRange": source_range,
        "outputRange": output_range,
        "sourceLayout": "stereo",
        "targetLayout": "stereo",
        "channelMap": [0, 1],
        "latencyCompensationSamples": 0,
    }
    graph["nodes"].append(node)
    graph["operations"].extend(
        [
            {
                "operationId": "trim-native-mix",
                "kind": "trim",
                "range": output_range,
                "parameters": {
                    "nodeId": "native-mix",
                    "sourceId": "native-original",
                    "source": {
                        "locator": str(source),
                        "sha256": fingerprint["sha256"],
                        "mediaClass": "source",
                        "ancestry": [],
                        "streamIndex": 0,
                    },
                },
            },
            {
                "operationId": "resample-native-mix",
                "kind": "resample",
                "range": output_range,
                "parameters": {
                    "nodeId": "native-mix",
                    "sourceSampleRate": 96000,
                    "targetSampleRate": 48000,
                },
            },
        ]
    )
    execution["canonicalInputLock"]["source:native-original"] = fingerprint["sha256"]
    execution["events"].append(
        {
            "eventId": "native-mix-event",
            "role": role,
            "programFrame": 30,
            "visibleRange": None,
            "sourceRange": source_range,
            "audio": {"nodeId": "native-mix"},
            "transientOffset": None,
            "resolvedImpactSample": 60000,
            "entryEffectIds": [],
            "validation": {"required": True},
        }
    )
    mixed = tmp_path / "mixed.mkv"
    micro = tmp_path / "micro.mkv"
    context = (
        proof_validation_batch(reuse_video_stages=True) if batch else nullcontext()
    )
    with context:
        execute_ffmpeg_proof(execution, mixed)
        execution["window"] = {"startFrame": 29, "endFrameExclusive": 43}
        execute_ffmpeg_proof(execution, micro)
    clean, actual = _decoded(baseline, audio=True), _decoded(mixed, audio=True)
    assert len(actual) == len(clean) == 192000
    np.testing.assert_allclose(actual[:60000], clean[:60000], atol=2e-7)
    np.testing.assert_allclose(actual[84000:], clean[84000:], atol=2e-7)
    delta = actual[62000:82000] - clean[62000:82000]
    np.testing.assert_allclose(delta[:, 0], 2000 / 32768, atol=2e-7)
    np.testing.assert_allclose(delta[:, 1], 4000 / 32768, atol=2e-7)
    np.testing.assert_allclose(
        _decoded(micro, audio=True), actual[58000:86000], atol=2e-7
    )
