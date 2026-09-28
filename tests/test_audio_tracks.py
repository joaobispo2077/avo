from __future__ import annotations

import pytest

from avo.adapters.media.audio_tracks import (
    AudioGraphError,
    compile_continuous_audio_graph,
)
from avo.timeline.tracks import TrackError, normalize_audio_track_layer


def source(
    node_id: str,
    source_start: int,
    source_end: int,
    output_start: int,
    output_end: int,
    **extra,
):
    return {
        "nodeId": node_id,
        "kind": "source",
        "input": {"sha256": "a" * 64, "streamId": "a:0", "locator": f"{node_id}.wav"},
        "sourceSampleRate": 44_100,
        "targetSampleRate": 48_000,
        "sourceLayout": "mono",
        "targetLayout": "stereo",
        "sourceSampleRange": {
            "startSample": source_start,
            "endSampleExclusive": source_end,
        },
        "outputSampleRange": {
            "startSample": output_start,
            "endSampleExclusive": output_end,
        },
        "channelMap": [0, 0],
        "latency": {"decoderSamples": 0, "resamplerSamples": 0, "filterSamples": 0},
        **extra,
    }


def test_continuous_graph_requires_explicit_silence_and_one_final_encode() -> None:
    first = source("dialogue-a", 0, 44_100, 0, 48_000)
    silence = {
        "nodeId": "room-tone-gap",
        "kind": "silence",
        "targetSampleRate": 48_000,
        "targetLayout": "stereo",
        "outputSampleRange": {"startSample": 48_000, "endSampleExclusive": 52_800},
        "channelMap": [0, 1],
    }
    second = source("dialogue-b", 44_100, 88_200, 52_800, 100_800)
    graph = compile_continuous_audio_graph(
        [first, silence, second],
        operations=[
            {
                "operationId": "encode-final",
                "kind": "encode",
                "range": {"startSample": 0, "endSampleExclusive": 100_800},
                "parameters": {"codec": "aac"},
            }
        ],
    )
    assert graph["singleFinalEncode"] is True
    assert graph["durationSamples"] == 100_800
    assert graph["nodes"][0]["expectedTargetSamples"] == 48_000


def test_gap_overlap_and_latency_mismatch_block_without_explicit_operation() -> None:
    with pytest.raises(AudioGraphError, match="gap"):
        compile_continuous_audio_graph(
            [source("a", 0, 44_100, 0, 48_000), source("b", 0, 44_100, 50_000, 98_000)],
            operations=[],
        )
    with pytest.raises(AudioGraphError, match="overlap"):
        compile_continuous_audio_graph(
            [source("a", 0, 44_100, 0, 48_000), source("b", 0, 44_100, 47_000, 95_000)],
            operations=[],
        )
    with pytest.raises(AudioGraphError, match="latency"):
        compile_continuous_audio_graph(
            [
                source(
                    "a",
                    0,
                    44_100,
                    0,
                    48_000,
                    latency={
                        "decoderSamples": 0,
                        "resamplerSamples": 12,
                        "filterSamples": 0,
                    },
                )
            ],
            operations=[],
        )


def test_declared_crossfade_and_approved_reconciliation_are_inspectable() -> None:
    graph = compile_continuous_audio_graph(
        [
            source("a", 0, 44_100, 0, 48_000),
            source(
                "b",
                0,
                44_100,
                47_000,
                95_000,
                latency={
                    "decoderSamples": 0,
                    "resamplerSamples": 12,
                    "filterSamples": 0,
                },
            ),
        ],
        operations=[
            {
                "operationId": "xfade",
                "kind": "crossfade",
                "range": {"startSample": 47_000, "endSampleExclusive": 48_000},
                "parameters": {},
            },
            {
                "operationId": "trim-latency",
                "kind": "trim",
                "range": {"startSample": 47_000, "endSampleExclusive": 95_000},
                "parameters": {"nodeId": "b", "approved": True, "samples": 12},
            },
            {
                "operationId": "encode-final",
                "kind": "encode",
                "range": {"startSample": 0, "endSampleExclusive": 95_000},
                "parameters": {},
            },
        ],
    )
    assert graph["overlaps"] == [
        {"startSample": 47_000, "endSampleExclusive": 48_000, "operationId": "xfade"}
    ]


def test_track_channel_mapping_is_explicit_and_preserves_source_audio_role() -> None:
    normalized = normalize_audio_track_layer(
        {
            "layerId": "insert",
            "role": "source-audio",
            "sourceLayout": "mono",
            "targetLayout": "stereo",
            "channelMap": [0, 0],
        }
    )
    assert normalized["channelMap"] == [0, 0]
    assert normalized["role"] == "source-audio"
    with pytest.raises(TrackError, match="channel map"):
        normalize_audio_track_layer(
            {
                "layerId": "bad",
                "role": "dialogue",
                "sourceLayout": "mono",
                "targetLayout": "stereo",
                "channelMap": [0, 1],
            }
        )
