from copy import deepcopy

import numpy as np
import pytest

from avo.breath_control import (
    BreathControlError,
    apply_control,
    cut_proposals,
    gain_envelope,
    resolve_control,
    select_events,
)


def control(**kwargs):
    return {
        "enabled": True,
        "action": "attenuate",
        "events": [
            {
                "eventId": "breath-001",
                "startSample": 200,
                "endSampleExclusive": 800,
                "status": "confirmed",
                "breathRmsDb": -20,
                "speechRmsDb": -10,
            }
        ],
        **kwargs,
    }


def test_opt_in_and_conservative_defaults():
    assert resolve_control(None) is None
    assert resolve_control({"enabled": False}) is None
    policy = resolve_control(control())
    assert policy["maxReductionDb"] == 9
    assert policy["targetBelowSpeechDb"] == 20
    with pytest.raises(BreathControlError, match="dialogue"):
        resolve_control(control(), role="music")


def test_hybrid_proposes_cuts_only_for_long_events():
    cfg = control(action="hybrid", longMs=700)
    cfg["events"][0]["rawAnchor"] = {
        "sourceId": "raw",
        "sampleRate": 1000,
        "startSample": 2000,
        "endSampleExclusive": 2600,
    }
    assert cut_proposals(cfg, 1000) == []


@pytest.mark.parametrize(
    "field,value", [("maxReductionDb", -1), ("guardMs", -2), ("longMs", float("nan"))]
)
def test_invalid_policy_fails_closed(field, value):
    with pytest.raises(BreathControlError):
        resolve_control(control(**{field: value}))


def test_does_not_process_ambiguous_rejected_or_protected_events():
    for status in ("ambiguous", "rejected"):
        cfg = control()
        cfg["events"][0]["status"] = status
        assert select_events(cfg, 1000) == []
    cfg = control(protectedRanges=[{"startSample": 750, "endSampleExclusive": 900}])
    assert select_events(cfg, 1000) == []


@pytest.mark.parametrize(
    "selector,expected",
    [
        ("all", 1),
        ("long", 1),
        ("heavy", 1),
        ("long-or-heavy", 1),
        ("long-and-heavy", 1),
        ("manual", 0),
    ],
)
def test_selectors(selector, expected):
    assert len(select_events(control(selection=selector), 1000)) == expected


def test_manual_selection_and_overlap_rejected():
    cfg = control(selection="manual")
    cfg["events"][0]["manual"] = True
    assert len(select_events(cfg, 1000)) == 1
    second = deepcopy(cfg["events"][0])
    second["eventId"] = "breath-002"
    cfg["events"].append(second)
    with pytest.raises(BreathControlError, match="overlap"):
        gain_envelope(cfg, 1000, 1000)


def test_attenuation_preserves_pcm_outside_event_and_channel_mapping():
    cfg = control(sampleRate=1000, fadeInMs=30, fadeOutMs=50)
    pcm = np.random.default_rng(1).normal(size=(1000, 2)).astype(np.float32)
    after, removed = apply_control(pcm, cfg, 1000)
    np.testing.assert_array_equal(after[:200], pcm[:200])
    np.testing.assert_array_equal(after[800:], pcm[800:])
    np.testing.assert_array_equal(removed[:200], 0)
    np.testing.assert_allclose(after + removed, pcm, atol=1e-6)
    assert after.shape == pcm.shape
    assert gain_envelope(cfg, 1000, 1000)[400] == pytest.approx(10 ** (-9 / 20))


def test_quiet_breaths_never_boosted_and_preserve_is_identity():
    cfg = control()
    cfg["events"][0]["breathRmsDb"] = -50
    np.testing.assert_array_equal(gain_envelope(cfg, 1000, 1000), 1)
    np.testing.assert_array_equal(
        gain_envelope(control(action="preserve"), 1000, 1000), 1
    )


def test_audio_only_processor_cannot_delete_time_or_invent_room_tone():
    for action in ("cut", "shorten", "hybrid"):
        with pytest.raises(BreathControlError, match="CMap"):
            apply_control(np.ones((1000, 2)), control(action=action), 1000)
    with pytest.raises(BreathControlError, match="room tone"):
        apply_control(np.ones((1000, 2)), control(action="room-tone"), 1000)


def test_room_tone_replacement_preserves_length_and_edges():
    cfg = control(action="room-tone", sampleRate=1000)
    pcm = np.ones((1000, 2), dtype=np.float32)
    tone = np.full_like(pcm, 0.01)
    after, _ = apply_control(pcm, cfg, 1000, room_tone=tone)
    assert after[400, 0] == pytest.approx(0.01)
    np.testing.assert_array_equal(after[:200], pcm[:200])


def test_cut_proposals_require_raw_anchors_and_return_only_safe_intervals():
    cfg = control(action="shorten", sampleRate=1000, keepPauseMs=250)
    with pytest.raises(BreathControlError, match="raw-source"):
        cut_proposals(cfg, 1000)
    cfg["events"][0]["rawAnchor"] = {
        "sourceId": "main",
        "startSample": 1200,
        "endSampleExclusive": 1800,
        "sampleRate": 1000,
    }
    proposals = cut_proposals(cfg, 1000)
    assert proposals[0]["sourceId"] == "main"
    assert proposals[0]["endSampleExclusive"] - proposals[0]["startSample"] == 350
    assert proposals[0]["requiresCMapApproval"]


def test_sample_rate_mismatch_and_out_of_bounds_block():
    with pytest.raises(BreathControlError, match="sample rate"):
        gain_envelope(control(sampleRate=48000), 1000, 1000)
    with pytest.raises(BreathControlError, match="range"):
        gain_envelope(control(), 500, 1000)
