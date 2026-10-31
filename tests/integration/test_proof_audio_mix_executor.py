"""Absolute mix events share the native proof's source and microproof clock."""

from copy import deepcopy

import numpy as np
import pytest
from tests.integration.test_ffmpeg_proof_executor import _execution, _pcm

from avo.adapters.media.proof_executor import execute_ffmpeg_proof


def _with_music(execution):
    value = deepcopy(execution)
    graph = value["audioGraph"]
    region = {"startSample": 24024, "endSampleExclusive": 48048}
    node = {
        **deepcopy(graph["nodes"][0]),
        "nodeId": "music-insert",
        "kind": "music",
        "sourceRange": {"startSample": 0, "endSampleExclusive": 24024},
        "outputRange": region,
        "channelMap": [1, 1],
    }
    graph["nodes"].append(node)
    source = deepcopy(graph["operations"][1]["parameters"])
    source["nodeId"] = node["nodeId"]
    graph["operations"].extend(
        [
            {
                "operationId": "music-trim",
                "kind": "trim",
                "range": region,
                "parameters": source,
            },
            {
                "operationId": "music-gain",
                "kind": "gain",
                "range": region,
                "parameters": {"nodeId": node["nodeId"], "gainDb": -20},
            },
            {
                "operationId": "program-mix",
                "kind": "mix",
                "range": {"startSample": 0, "endSampleExclusive": 96096},
                "parameters": {"nodeIds": [n["nodeId"] for n in graph["nodes"]]},
            },
        ]
    )
    value["events"].append(
        {
            "eventId": "music-event",
            "role": "music",
            "programFrame": 15,
            "visibleRange": None,
            "sourceRange": node["sourceRange"],
            "audio": {"nodeId": node["nodeId"]},
            "transientOffset": None,
            "resolvedImpactSample": 24024,
            "entryEffectIds": [],
            "validation": {"required": True},
        }
    )
    return value


def test_mix_preserves_voice_outside_music_and_microproof_absolute_clock(tmp_path):
    execution = _execution(tmp_path)
    execution["output"].update(
        conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le"
    )
    baseline = tmp_path / "baseline.mkv"
    execute_ffmpeg_proof(execution, baseline)
    mixed = _with_music(execution)
    output = tmp_path / "mixed.mkv"
    execute_ffmpeg_proof(mixed, output)
    clean, result = _pcm(baseline), _pcm(output)
    assert len(result) == len(clean) == 96096
    np.testing.assert_allclose(result[:20000], clean[:20000], atol=2e-7)
    np.testing.assert_allclose(result[50000:], clean[50000:], atol=2e-7)
    assert np.sqrt(np.mean((result[26000:45000] - clean[26000:45000]) ** 2)) > 0.003
    mixed["window"] = {"startFrame": 12, "endFrameExclusive": 33}
    micro = tmp_path / "micro.mkv"
    execute_ffmpeg_proof(mixed, micro)
    np.testing.assert_allclose(_pcm(micro), result[19219:52853], atol=2e-7)


def test_audio_event_cannot_reference_missing_mix_node(tmp_path):
    execution = _with_music(_execution(tmp_path))
    execution["events"][-1]["audio"]["nodeId"] = "not-declared"
    target = tmp_path / "must-not-exist.mp4"
    with pytest.raises(RuntimeError, match="event|node"):
        execute_ffmpeg_proof(execution, target)
    assert not target.exists()


@pytest.mark.parametrize("delta", [-272, 432])
def test_mix_keeps_native_dialogue_source_ranges_at_frame_conformance(tmp_path, delta):
    execution = _execution(tmp_path)
    execution["output"].update(
        conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le"
    )
    original = deepcopy(execution["audioGraph"]["nodes"][0]["sourceRange"])
    execution["audioGraph"]["nodes"][0]["sourceRange"]["endSampleExclusive"] += delta
    retained = deepcopy(execution["audioGraph"]["nodes"][0]["sourceRange"])
    baseline = tmp_path / "native-conformed.mkv"
    execute_ffmpeg_proof(execution, baseline)
    mixed = _with_music(execution)
    output = tmp_path / "native-conformed-mix.mkv"
    execute_ffmpeg_proof(mixed, output)
    result, clean = _pcm(output), _pcm(baseline)
    assert len(result) == len(clean) == 96096
    np.testing.assert_allclose(result[:20000], clean[:20000], atol=2e-7)
    assert mixed["audioGraph"]["nodes"][0]["sourceRange"] == retained
    assert retained != original


def test_mix_rejects_dialogue_conformance_beyond_native_frame_budget(tmp_path):
    execution = _with_music(_execution(tmp_path))
    execution["audioGraph"]["nodes"][0]["sourceRange"]["endSampleExclusive"] += 2000
    target = tmp_path / "excess-conformance.mp4"
    with pytest.raises(ValueError, match="one video frame"):
        execute_ffmpeg_proof(execution, target)
    assert not target.exists()
