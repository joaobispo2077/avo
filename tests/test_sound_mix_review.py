"""Sound review binds measured PCM to its exact selected proof window."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.materialize import _render_required_microproofs
from avo.timeline.sound_mix_review import summarize_sound_mix


@pytest.fixture
def program():
    nodes = [
        {
            "nodeId": identity,
            "kind": "sfx",
            "outputRange": {"startSample": start, "endSampleExclusive": end},
        }
        for identity, start, end in (
            ("early", 800, 1600),
            ("hit", 1600, 2400),
            ("tail", 3200, 4000),
        )
    ]
    plan = {
        "proofPlanHash": "a" * 64,
        "output": {"frameRate": {"num": 30, "den": 1}, "audioSampleRate": 48000},
        "events": [
            {"eventId": node["nodeId"], "audio": {"nodeId": node["nodeId"]}}
            for node in nodes
        ],
        "audioGraph": {
            "nodes": nodes,
            "operations": [
                {
                    "kind": "encode",
                    "range": {"startSample": 0, "endSampleExclusive": 6400},
                }
            ],
        },
    }
    rendered = {
        "output": {"sha256": "b" * 64},
        "audioMix": {
            "output": {"sha256": "c" * 64, "locator": "private-mix.wav"},
            "sampleRate": 48000,
            "channels": 2,
            "sampleCount": 1600,
            "window": {"startSample": 1600, "endSampleExclusive": 3200},
            "measurement": {"peakDbfs": 1.25, "rmsDbfs": -14.0},
            "graphHash": "d" * 64,
            "inputGraphHash": content_hash(plan["audioGraph"]),
            "pcmCodec": "pcm_f32le",
        },
    }
    return plan, rendered, {"startFrame": 1, "endFrameExclusive": 2}


def test_summary_reports_exact_peak_and_only_sounds_in_half_open_window(program):
    plan, rendered, window = program
    receipt = summarize_sound_mix(plan, rendered, window)
    assert receipt == {
        "status": "measured",
        "assessment": "pre-encode-pcm-sample-peak",
        "eventIds": ["hit"],
        "sampleRate": 48000,
        "channels": 2,
        "window": rendered["audioMix"]["window"],
        "proofPlanHash": "a" * 64,
        "candidateSha256": "b" * 64,
        "mixGraphHash": "d" * 64,
        "pcmSha256": "c" * 64,
        "peakDbfs": 1.25,
        "rmsDbfs": -14.0,
        "fullScaleHeadroomDb": -1.25,
        "aboveFullScale": True,
    }


@pytest.mark.parametrize(
    "mismatch", ["missing", "window", "rate", "finite", "shape", "previous-graph"]
)
def test_summary_discloses_missing_or_unqualified_native_measurement(program, mismatch):
    plan, rendered, window = program
    if mismatch == "missing":
        rendered.pop("audioMix")
    elif mismatch == "window":
        rendered["audioMix"]["window"]["startSample"] -= 1
    elif mismatch == "rate":
        rendered["audioMix"]["sampleRate"] = 44100
    elif mismatch == "shape":
        rendered["audioMix"]["measurement"] = ["peakDbfs", "rmsDbfs"]
    elif mismatch == "previous-graph":
        plan["audioGraph"]["nodes"][1]["gainDb"] = -9
    else:
        rendered["audioMix"]["measurement"]["peakDbfs"] = float("nan")
    receipt = summarize_sound_mix(plan, rendered, window)
    assert receipt["status"] == "unavailable"
    assert receipt["eventIds"] == ["hit"]
    assert "peakDbfs" not in receipt


def test_summary_skips_unrelated_window_and_preserves_full_mix_identity(program):
    plan, rendered, _ = program
    assert (
        summarize_sound_mix(plan, rendered, {"startFrame": 3, "endFrameExclusive": 4})
        is None
    )
    before = deepcopy(plan)
    rendered["audioMix"].update(
        window={"startSample": 0, "endSampleExclusive": 6400},
        sampleCount=6400,
        measurement={"peakDbfs": None, "rmsDbfs": None},
    )
    receipt = summarize_sound_mix(plan, rendered, None)
    assert receipt["eventIds"] == ["early", "hit", "tail"]
    assert receipt["peakDbfs"] is None
    assert receipt["aboveFullScale"] is False
    assert plan == before


def test_required_proof_window_retains_measurement_with_verified_candidate(
    tmp_path, program
):
    plan, rendered, window = program

    def render(request, path, *, window):
        path.write_bytes(b"measured proof fixture")
        return {**rendered, "output": file_fingerprint(path)}

    port = SimpleNamespace(render_proof_plan=render)
    required = {**window, "reasons": ["timed-event"], "operationIds": ["hit"]}
    (result,) = _render_required_microproofs(port, plan, [required], tmp_path, ".mkv")
    evidence = result["soundMixReview"]
    assert evidence["eventIds"] == ["hit"]
    assert evidence["candidateSha256"] == result["output"]["sha256"]
    assert evidence["aboveFullScale"] is True


@pytest.mark.parametrize("stale", [False, True])
def test_dialogue_balance_binds_selected_effect_margin_and_exact_overlap(
    program, stale
):
    plan, rendered, window = program
    plan["audioGraph"]["operations"].append(
        {"kind": "duck", "parameters": {"nodeId": "hit", "minimumDialogueMarginDb": 12}}
    )
    rendered["audioMix"]["inputGraphHash"] = content_hash(plan["audioGraph"])
    observed = {
        "nodeId": "hit",
        "minimumDialogueMarginDb": 12,
        "bandHz": [300, 4000],
        "window": {
            "startSample": 1600,
            "endSampleExclusive": 2400 if not stale else 2399,
        },
        "status": "measured",
        "dialogueRmsDbfs": -16.0,
        "effectRmsDbfs": -22.0,
    }
    rendered["audioMix"]["dialogueBalance"] = [
        observed,
        {**observed, "nodeId": "unknown"},
    ]
    (review,) = summarize_sound_mix(plan, rendered, window)["dialogueBalance"]
    assert review["eventId"] == "hit"
    assert review["window"] == {"startSample": 1600, "endSampleExclusive": 2400}
    if stale:
        assert review["status"] == "measurement-unavailable"
        assert "suggestedAdditionalAttenuationDb" not in review
    else:
        assert review["status"] == "below-selected-margin"
        assert review["suggestedAdditionalAttenuationDb"] == 6.0
