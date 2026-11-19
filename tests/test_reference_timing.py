"""Timing candidates preserve native intervals and label approximate fits."""

from itertools import pairwise

import pytest

from avo.reference_timing import interpret_reference_timing

SCOPE = {"timebase": {"num": 1, "den": 1000}}


def motion(x=0, *, moving=0):
    return {
        "status": "measured",
        "global": {"scale": 1, "rotationDegrees": 0, "translateX": x, "translateY": 0},
        "residual": {"p90DisplayDiagonal": 0, "movingPoints": moving},
    }


def test_visual_hold_and_reveal_candidates_cannot_cross_unmeasured_intervals():
    ticks = [4000, 4010, 4050, 4080, 4200, 4240, 4300]
    rows = [
        motion(),
        motion(),
        motion(moving=8),
        {"status": "unmeasurable"},
        motion(),
        motion(0.1),
    ]
    result = interpret_reference_timing(
        ticks, rows, {"hold-reveal", "audio-word-timing"}, SCOPE
    )
    assert result["availableEvidence"] == {
        "hold-reveal": "measured-candidates",
        "audio-word-timing": "unavailable",
        "prepared-words": "not-selected",
    }
    assert result["timingCandidates"] == [
        {
            "kind": "hold",
            "startTicks": 4000,
            "endTicks": 4050,
            "evidence": "low-motion",
        },
        {
            "kind": "reveal",
            "startTicks": 4050,
            "endTicks": 4080,
            "evidence": "motion-onset",
        },
    ]
    assert result["easing"] == "uninterpreted"


def test_easing_fit_uses_measured_native_step_times_and_labels_approximation():
    ticks = [500, 510, 540, 562, 590, 600]
    positions = [((tick - 500) / 100) ** 2 / 3 for tick in ticks]
    rows = [motion(last - first) for first, last in pairwise(positions)]
    result = interpret_reference_timing(ticks, rows, {"easing"}, SCOPE)
    assert result["easing"] == {
        "status": "approximate",
        "curve": "quadratic-in",
        "axis": "translateX",
        "startTicks": 500,
        "endTicks": 600,
        "progressRmse": pytest.approx(0, abs=1e-10),
    }
    rows[2] = {"status": "cut-candidate"}
    assert (
        interpret_reference_timing(ticks, rows, {"easing"}, SCOPE)["easing"]
        == "uninterpreted"
    )


def test_audio_candidates_use_absolute_sample_clock_and_keep_window_uncertainty():
    ticks = [4000, 4010, 4050, 4080]
    rows = [motion(), motion(), motion(0.1)]
    audio = {
        "status": "observed",
        "sampleRate": 48_000,
        "onsetSamples": [193_000, 194_350, 194_700, 200_000],
        "clockUncertaintySamples": 1,
        "windowSamples": 480,
    }
    result = interpret_reference_timing(
        ticks, rows, {"audio-word-timing"}, SCOPE, audio=audio
    )
    assert result["audioRevealRelationships"] == [
        {"startTicks": 4050, "endTicks": 4080, "onsetSamples": [194_350, 194_700]}
    ]


def test_fade_candidate_requires_multiple_directional_steps_and_stops_at_cut():
    ticks = [0, 40, 80, 120, 160, 200, 240]
    steps = [(0.6, 0.5), (0.5, 0.4), (0.4, 0.3), (0.3, 0.9), (0.9, 0.55), (0.55, 0.5)]
    rows = [
        {
            "status": "cut-candidate" if index == 3 else "unmeasurable",
            "brightness": {"before": before, "after": after},
        }
        for index, (before, after) in enumerate(steps)
    ]
    result = interpret_reference_timing(ticks, rows, {"brightness"}, SCOPE)
    assert result["fadeCandidates"] == [
        {
            "direction": "darkening",
            "startTicks": 0,
            "endTicks": 120,
            "before": 0.6,
            "after": 0.3,
        }
    ]
