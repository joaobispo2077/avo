from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.timeline.initial_cut import initial_cut_proof_request


def workspace(tmp_path):
    sources = []
    segments = []
    for index, channels in enumerate(([0], [0, 1]), 1):
        source_id = f"source-{index}"
        sources.append(
            {
                "sourceId": source_id,
                "locator": str(tmp_path / f"camera-{index}.mkv"),
                "fingerprint": {"sha256": str(index) * 64},
                "streamMetadata": {
                    "videoStreamIndex": 0,
                    "audioSelection": {
                        "streamIndex": 2 if index == 1 else 1,
                        "channels": channels,
                        "sourceLayout": "stereo",
                        "sourceSampleRate": 48000,
                        "outputLayout": "dual-mono" if index == 1 else "stereo",
                    },
                },
            }
        )
        segments.append(
            {
                "segmentId": f"segment-{index}",
                "sourceId": source_id,
                "in": {"ticks": 1000, "timebase": {"num": 1, "den": 1000}},
                "out": {"ticks": 9000, "timebase": {"num": 1, "den": 1000}},
            }
        )
    snapshot = {
        "sources": sources,
        "segments": segments,
        "protectedQuizWindows": [
            {
                "sourceBasename": "camera-1.mkv",
                "start": 2,
                "end": 7,
                "minimumAnswerSeconds": 5,
            }
        ],
    }
    store = SimpleNamespace(revision=lambda _: {"snapshot": snapshot})
    return SimpleNamespace(
        require_active=lambda _: {"headRevisionId": "cmap-r0001"},
        store=lambda _: store,
        raw_dir=tmp_path,
    ), snapshot


def test_initial_request_preserves_per_source_audio_and_answer_window(tmp_path):
    project, _ = workspace(tmp_path)
    request = initial_cut_proof_request(
        project,
        iteration_id="iteration-0001",
        output=tmp_path / "proof.mp4",
        frame_rate={"num": 60, "den": 1},
    )
    assert request["checkpoint"] == "cut-proof"
    nodes = request["audioGraph"]["nodes"]
    assert [node["channelMap"] for node in nodes] == [[0, 0], [0, 1]]
    audio_ops = request["audioGraph"]["operations"]
    assert [op["parameters"]["source"]["streamIndex"] for op in audio_ops[:-1]] == [
        2,
        1,
    ]
    assert audio_ops[0]["parameters"]["fadeInSamples"] == 1440
    assert audio_ops[-1]["range"]["endSampleExclusive"] == 16 * 48000
    assert {"startFrame": 60, "endFrameExclusive": 360} in request["validationPlan"][
        "microproof"
    ]
    assert {"startFrame": 360, "endFrameExclusive": 600} in request["validationPlan"][
        "microproof"
    ]


@pytest.mark.parametrize("start,end", [(3000, 9000), (1000, 6500), (1000, 1000)])
def test_initial_request_rejects_cut_protected_answer_or_empty_interval(
    tmp_path, start, end
):
    project, snapshot = workspace(tmp_path)
    snapshot["segments"][0]["in"]["ticks"] = start
    snapshot["segments"][0]["out"]["ticks"] = end
    with pytest.raises(ValueError):
        initial_cut_proof_request(
            project,
            iteration_id="iteration-0001",
            output=Path("proof.mp4"),
            frame_rate={"num": 25, "den": 1},
        )


def test_initial_request_quantizes_cumulative_rational_clock_without_drift(tmp_path):
    project, snapshot = workspace(tmp_path)
    snapshot["protectedQuizWindows"] = []
    base = snapshot["segments"][0]
    base["out"]["ticks"] = 1037
    snapshot["segments"] = [deepcopy(base) for _ in range(100)]
    request = initial_cut_proof_request(
        project,
        iteration_id="iteration-0001",
        output=tmp_path / "proof.mp4",
        frame_rate={"num": 30000, "den": 1001},
    )
    assert (
        request["videoGraph"]["operations"][-1]["outputRange"]["endFrameExclusive"]
        == 111
    )
    assert (
        request["audioGraph"]["nodes"][-1]["outputRange"]["endSampleExclusive"]
        == 177778
    )


def test_initial_request_declares_native_source_samples_and_resampling(tmp_path):
    project, snapshot = workspace(tmp_path)
    snapshot["sources"][1]["streamMetadata"]["audioSelection"]["sourceSampleRate"] = (
        44100
    )
    request = initial_cut_proof_request(
        project,
        iteration_id="iteration-0001",
        output=tmp_path / "proof.mp4",
        frame_rate={"num": 60, "den": 1},
    )
    node = request["audioGraph"]["nodes"][1]
    assert node["sourceSampleRate"] == 44100
    assert node["sourceRange"] == {"startSample": 44100, "endSampleExclusive": 396900}
    resample = next(
        op for op in request["audioGraph"]["operations"] if op["kind"] == "resample"
    )
    assert resample["range"] == node["outputRange"]
    assert resample["parameters"] == {
        "nodeId": node["nodeId"],
        "sourceSampleRate": 44100,
        "targetSampleRate": 48000,
    }


def test_initial_request_nr_is_scoped_to_canonical_dialogue_source(tmp_path):
    project, snapshot = workspace(tmp_path)
    policy = {
        "mode": "afftdn",
        "role": "presenter-dialogue",
        "strengthPercent": 60,
        "streamIndex": 2,
        "channelIndex": 0,
        "approvedByUser": True,
    }
    snapshot["sources"][0]["streamMetadata"]["dialogueNoiseReductionPolicy"] = policy
    request = initial_cut_proof_request(
        project,
        iteration_id="iteration-0001",
        output=tmp_path / "proof.mp4",
        frame_rate={"num": 60, "den": 1},
    )
    trims = [op for op in request["audioGraph"]["operations"] if op["kind"] == "trim"]
    assert trims[0]["parameters"]["dialogueNoiseReductionPolicy"] == policy
    assert "dialogueNoiseReductionPolicy" not in trims[1]["parameters"]
    assert all(
        "dialogueNoiseReductionPolicy" not in op["parameters"]
        for op in request["videoGraph"]["operations"]
    )
    policy["strengthPercent"] = 40
    assert (
        trims[0]["parameters"]["dialogueNoiseReductionPolicy"]["strengthPercent"] == 60
    )


def test_short_fragment_bounds_fades_without_changing_raw_source_interval(tmp_path):
    project, snapshot = workspace(tmp_path)
    snapshot["protectedQuizWindows"] = []
    snapshot["segments"] = snapshot["segments"][:1]
    snapshot["segments"][0]["out"]["ticks"] = 1020
    request = initial_cut_proof_request(
        project,
        iteration_id="iteration-short",
        output=tmp_path / "proof.mp4",
        frame_rate={"num": 60, "den": 1},
    )
    node = request["audioGraph"]["nodes"][0]
    trim = request["audioGraph"]["operations"][0]
    assert (
        node["sourceRange"]["endSampleExclusive"] - node["sourceRange"]["startSample"]
        == 960
    )
    assert (
        node["outputRange"]["endSampleExclusive"] - node["outputRange"]["startSample"]
        == 800
    )
    assert trim["parameters"]["fadeInSamples"] == 400
    assert trim["parameters"]["fadeOutSamples"] == 400
