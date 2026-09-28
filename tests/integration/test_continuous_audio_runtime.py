from __future__ import annotations

from avo.adapters.media.audio_tracks import compile_continuous_audio_graph
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.timeline.review import audio_editlog_entry, write_audio_editlog_entry
from avo.timeline.review_runner import compare_protected_boundaries


def test_many_segment_audio_stays_absolute_and_reviewable(tmp_path) -> None:
    nodes = []
    for index in range(20):
        start = index * 4_800
        nodes.append(
            {
                "nodeId": f"word-{index}",
                "kind": "source",
                "input": {
                    "sha256": "a" * 64,
                    "streamId": "a:0",
                    "locator": "dialogue.wav",
                },
                "sourceSampleRate": 48_000,
                "targetSampleRate": 48_000,
                "sourceLayout": "mono",
                "targetLayout": "mono",
                "sourceSampleRange": {
                    "startSample": start,
                    "endSampleExclusive": start + 4_800,
                },
                "outputSampleRange": {
                    "startSample": start,
                    "endSampleExclusive": start + 4_800,
                },
                "channelMap": [0],
                "latency": {
                    "decoderSamples": 0,
                    "resamplerSamples": 0,
                    "filterSamples": 0,
                },
            }
        )
    graph = compile_continuous_audio_graph(
        nodes,
        operations=[
            {
                "operationId": "encode-final",
                "kind": "encode",
                "range": {"startSample": 0, "endSampleExclusive": 96_000},
                "parameters": {},
            }
        ],
    )
    assert graph["durationSamples"] == 96_000
    assert graph["nodes"][-1]["outputSampleRange"]["endSampleExclusive"] == 96_000
    review = compare_protected_boundaries(
        {"words": [{"word": "signoff", "start": 1.9, "end": 2.0}]},
        {"words": [{"word": "signoff", "start": 1.9, "end": 2.0}]},
        protected_boundaries=[
            {
                "boundaryId": "signoff",
                "kind": "phrase",
                "text": "signoff",
                "start": 1.9,
                "end": 2.0,
            }
        ],
        acoustic_checks={"signoff": {"confidence": 1.0, "complete": True}},
    )
    entry = audio_editlog_entry(
        graph, candidate_sha256="b" * 64, boundary_review=review, actor="avo"
    )
    assert entry["graphHash"] == graph["graphHash"]
    assert entry["exactExportReview"]["status"] == "pass"
    path = write_audio_editlog_entry(tmp_path / "AUDIO-EDITLOG.md", entry)
    assert graph["graphHash"] in path.read_text(encoding="utf-8")


def test_render_adapter_binds_one_final_encode_to_output(tmp_path, monkeypatch) -> None:
    projection = tmp_path / "projection.json"
    projection.write_text("{}", encoding="utf-8")
    output = tmp_path / "proof.mp4"
    node = {
        "nodeId": "dialogue",
        "kind": "source",
        "input": {
            "sha256": "a" * 64,
            "streamId": "a:0",
            "locator": "dialogue.wav",
        },
        "sourceSampleRate": 48_000,
        "targetSampleRate": 48_000,
        "sourceLayout": "mono",
        "targetLayout": "mono",
        "sourceSampleRange": {"startSample": 0, "endSampleExclusive": 4_800},
        "outputSampleRange": {"startSample": 0, "endSampleExclusive": 4_800},
        "channelMap": [0],
        "latency": {
            "decoderSamples": 0,
            "resamplerSamples": 0,
            "filterSamples": 0,
        },
    }
    operations = [
        {
            "operationId": "encode-final",
            "kind": "encode",
            "range": {"startSample": 0, "endSampleExclusive": 4_800},
            "parameters": {},
        }
    ]

    def fake_render() -> None:
        output.write_bytes(b"candidate")

    monkeypatch.setattr("avo.render.main", fake_render)
    result = TimelineRenderAdapter().render(
        projection,
        output,
        audio_graph={"sampleRate": 48_000, "nodes": [node], "operations": operations},
    )
    assert result["audioEncodeCount"] == 1
    assert result["audioGraphHash"]
