"""Canonical source-scoped NR rejects ambiguous routing and authorizes strong settings."""

import pytest

from avo.audio_restoration import validate_dialogue_noise_policy


def policy():
    return {
        "mode": "afftdn",
        "role": "presenter-dialogue",
        "strengthPercent": 50,
        "streamIndex": 2,
        "channelIndex": 0,
        "approvedByUser": True,
    }


def test_valid_policy_is_copied_and_calibrated():
    value = policy()
    assert validate_dialogue_noise_policy(value, 2, [0, 0]) == value
    assert validate_dialogue_noise_policy(value, 2, [0, 0]) is not value


@pytest.mark.parametrize(
    "change",
    [
        {"strengthPercent": True},
        {"strengthPercent": -1},
        {"strengthPercent": 101},
        {"strengthPercent": 60, "approvedByUser": False},
        {"mode": "unknown"},
        {"role": "game"},
        {"channelIndex": True},
        {"streamIndex": True},
        {"channelIndex": 1},
        {"streamIndex": 1},
        {"extra": 1},
    ],
)
def test_policy_fail_closed(change):
    value = policy()
    value.update(change)
    with pytest.raises(ValueError):
        validate_dialogue_noise_policy(value, 2, [0, 0])


def test_policy_requires_centered_single_channel():
    with pytest.raises(ValueError):
        validate_dialogue_noise_policy(policy(), 2, [0, 1])
