import subprocess
from copy import deepcopy

import numpy as np
import pytest

from avo.audio_restoration import (
    dialogue_treatment_filter,
    validate_dialogue_treatment_policy,
)


def policy():
    return {
        "mode": "clarity-v1",
        "role": "presenter-dialogue",
        "approvedByUser": True,
        "highpassHz": 80,
        "compression": {
            "thresholdDb": -26,
            "ratio": 3,
            "attackMs": 15,
            "releaseMs": 100,
        },
        "makeupGainDb": 0,
        "limiter": {
            "ceilingDbfs": -3,
            "attackMs": 5,
            "releaseMs": 50,
            "latencyCompensated": True,
        },
    }


def process(samples, treatment):
    samples = np.asarray(samples, dtype="<f4")
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "f32le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-i",
            "pipe:0",
            "-af",
            dialogue_treatment_filter(treatment),
            "-f",
            "f32le",
            "pipe:1",
        ],
        input=samples.tobytes(),
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype="<f4").reshape(-1, 2)


def test_compensated_limiter_preserves_quiet_impulse_and_broadband_samples():
    samples = np.random.default_rng(123).normal(0, 0.001, (9600, 2))
    samples[:, 1] = samples[:, 0]
    samples[1000] = 0.05
    treatment = policy()
    treatment["highpassHz"] = 0
    treatment["compression"]["ratio"] = 1
    output = process(samples, treatment)
    assert output.shape == samples.shape
    assert np.argmax(abs(output[:, 0])) == 1000
    np.testing.assert_allclose(output, samples, atol=1e-7)


def test_limiter_attenuates_transient_without_losing_dualmono_samples():
    samples = np.zeros((9600, 2))
    samples[1000:1100] = 2
    treatment = policy()
    treatment["highpassHz"] = 0
    treatment["compression"]["ratio"] = 1
    output = process(samples, treatment)
    assert output.shape == samples.shape
    assert np.isfinite(output).all()
    assert np.max(abs(output)) <= 10 ** (-3 / 20) + 1e-6
    assert np.max(abs(output)) > 0.5
    np.testing.assert_array_equal(output[:, 0], output[:, 1])


def test_highpass_reduces_rumble_and_retains_speech_band():
    t = np.arange(48000) / 48000
    source = 0.01 * np.sin(2 * np.pi * 20 * t) + 0.01 * np.sin(2 * np.pi * 1000 * t)
    treatment = policy()
    treatment["compression"]["ratio"] = 1
    output = process(np.column_stack([source, source]), treatment)[4800:, 0]
    spectrum = abs(np.fft.rfft(output))
    low = spectrum[18]
    speech = spectrum[900]
    assert low < speech * 0.1
    assert speech > 180


def test_compression_reduces_loud_speech_and_makeup_is_literal():
    t = np.arange(96000) / 48000
    amplitude = np.where(t < 1, 0.01, 0.4)
    source = amplitude * np.sin(2 * np.pi * 1000 * t)
    treatment = policy()
    treatment["highpassHz"] = 0
    output = process(np.column_stack([source, source]), treatment)[:, 0]
    quiet_rms = np.sqrt(np.mean(output[24000:40000] ** 2))
    loud_rms = np.sqrt(np.mean(output[72000:90000] ** 2))
    assert 3 < loud_rms / quiet_rms < 15
    treatment["compression"]["ratio"] = 1
    treatment["makeupGainDb"] = 6
    quiet = np.column_stack([source[:24000], source[:24000]])
    gained = process(quiet, treatment)
    np.testing.assert_allclose(gained, quiet * 10 ** (6 / 20), atol=1e-7)


@pytest.mark.parametrize(
    "path,value",
    [
        (("approvedByUser",), False),
        (("highpassHz",), True),
        (("highpassHz",), 20),
        (("makeupGainDb",), float("nan")),
        (("makeupGainDb",), float("inf")),
        (("compression", "ratio"), 7),
        (("compression", "thresholdDb"), "-26"),
        (("limiter", "latencyCompensated"), False),
        (("limiter", "ceilingDbfs"), 0),
        (("limiter", "attackMs"), False),
    ],
)
def test_rejects_unsafe_or_unapproved_values(path, value):
    treatment = policy()
    target = treatment
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_dialogue_treatment_policy(treatment)


def test_exact_policy_and_nested_keys_are_required_and_copy_is_independent():
    treatment = policy()
    returned = validate_dialogue_treatment_policy(treatment)
    assert returned == treatment
    returned["compression"]["ratio"] = 2
    assert treatment["compression"]["ratio"] == 3
    bad = deepcopy(treatment)
    bad["limiter"]["filter"] = "arbitrary"
    with pytest.raises(ValueError):
        dialogue_treatment_filter(bad)
    treatment["mode"] = "other"
    with pytest.raises(ValueError):
        validate_dialogue_treatment_policy(treatment)
