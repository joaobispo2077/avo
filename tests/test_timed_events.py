from __future__ import annotations

import pytest

from avo.timeline.event_clock import EventClockError, resolve_timed_event


def _event(**overrides):
    value = {
        "eventId": "insert-cai",
        "role": "overlay-image",
        "programFrame": 300,
        "visibleRange": {"startFrame": 295, "endFrameExclusive": 360},
        "sourceRange": None,
        "audio": None,
        "transientOffset": {
            "sourceSamples": 240,
            "sourceRate": 48_000,
            "resolvedOutputSamples": 240,
        },
        "entryEffectIds": ["pop-cai"],
        "validation": {"expectedOccurrences": 1},
    }
    value.update(overrides)
    return value


def _resolve(event):
    return resolve_timed_event(
        event, frame_rate_num=30_000, frame_rate_den=1_001, sample_rate=48_000
    )


def test_event_uses_one_frame_clock_for_visual_impact_and_transient_start() -> None:
    event = _resolve(_event())
    assert event["resolvedImpactSample"] == 480_480
    assert event["scheduledAudioStartSample"] == 480_240
    assert event["transientOffset"]["resolvedOutputSamples"] == 240


def test_overlay_video_can_retain_source_audio_and_one_entry_effect() -> None:
    event = _resolve(
        _event(
            role="overlay-video",
            sourceRef="walk.mp4",
            sourceRange={"startFrame": 0, "endFrameExclusive": 90},
            audio={"retainSourceAudio": True, "gainDb": -9},
        )
    )
    assert event["audio"]["retainSourceAudio"] is True


def test_main_scene_has_no_automatic_synthetic_effect() -> None:
    event = _event(
        role="main-scene",
        sourceRef="cutscene.mp4",
        sourceRange={"startFrame": 0, "endFrameExclusive": 90},
        entryEffectIds=[],
        transientOffset=None,
    )
    assert _resolve(event)["entryEffectIds"] == []
    with pytest.raises(EventClockError, match="require approval"):
        _resolve({**event, "entryEffectIds": ["pop"]})
    approved = _resolve(
        {**event, "entryEffectIds": ["impact"], "syntheticEffectApproved": True}
    )
    assert approved["entryEffectIds"] == ["impact"]


def test_multiple_overlay_effects_require_explicit_ordered_sequence() -> None:
    with pytest.raises(EventClockError, match="ordered sequence"):
        _resolve(_event(entryEffectIds=["huh", "vine-boom"]))
    event = _resolve(
        _event(entryEffectIds=["huh", "vine-boom"], orderedMultiEffect=True)
    )
    assert event["entryEffectIds"] == ["huh", "vine-boom"]


@pytest.mark.parametrize(
    "event",
    [
        _event(eventId=""),
        _event(role="unknown"),
        _event(programFrame=-1),
        _event(visibleRange={"startFrame": 2, "endFrameExclusive": 2}),
        _event(sourceRef="insert.mp4", sourceRange=None),
        _event(entryEffectIds=["pop", "pop"]),
        _event(
            transientOffset={
                "sourceSamples": 1,
                "sourceRate": 2,
                "resolvedOutputSamples": 0,
            }
        ),
    ],
)
def test_invalid_event_contracts_fail_closed(event) -> None:
    with pytest.raises(EventClockError):
        _resolve(event)


def test_comparison_only_event_remains_valid_review_evidence() -> None:
    event = _resolve(
        _event(role="comparison-only", entryEffectIds=[], transientOffset=None)
    )
    assert event["role"] == "comparison-only"
