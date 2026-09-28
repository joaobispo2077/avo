from __future__ import annotations

import pytest

from avo.adapters.media.video_tracks import verify_video_movement
from avo.adapters.media.waveform import verify_rendered_transients
from avo.timeline.event_clock import resolve_timed_event
from avo.timeline.review import event_audit_entry
from avo.timeline.review_runner import verify_exact_export_events
from avo.timeline.tracks import TrackError, apply_event_role_defaults


def test_visual_entry_audio_transient_and_movement_share_one_event_clock() -> None:
    event = apply_event_role_defaults(
        {
            "eventId": "overlay-001",
            "role": "overlay-video",
            "programFrame": 30,
            "visibleRange": {"startFrame": 30, "endFrameExclusive": 90},
            "sourceRange": {"startFrame": 0, "endFrameExclusive": 60},
            "sourceRef": "insert",
            "audio": {"retainSourceAudio": True},
            "transientOffset": {"sourceSamples": 240, "sourceRate": 48_000},
            "entryEffectIds": ["pop"],
            "validation": {"expectedOccurrences": 1},
        }
    )
    resolved = resolve_timed_event(
        event, frame_rate_num=30, frame_rate_den=1, sample_rate=48_000
    )
    wave = verify_rendered_transients(
        [resolved],
        {
            "overlay-001": [
                {"sample": resolved["resolvedImpactSample"] + 100, "confidence": 0.98}
            ]
        },
        tolerance_samples=1_600,
    )
    movement = verify_video_movement(
        "overlay-001", ["f1", "f2", "f3"], expected_motion=True
    )
    review = verify_exact_export_events(
        [resolved], transient_result=wave, movement_results=[movement]
    )
    assert resolved["scheduledAudioStartSample"] == 47_760
    assert review["status"] == "pass"
    audit = event_audit_entry(
        candidate_sha256="c" * 64, events=[resolved], exact_export_review=review
    )
    assert audit["events"][0]["eventId"] == "overlay-001"
    assert audit["events"][0]["observedMatches"][0]["offsetSamples"] == 100


def test_low_confidence_exact_export_match_requires_human_listening() -> None:
    event = {
        "eventId": "card",
        "resolvedImpactSample": 10_000,
        "validation": {"expectedOccurrences": 1},
    }
    wave = verify_rendered_transients(
        [event],
        {"card": [{"sample": 10_000, "confidence": 0.2, "masked": True}]},
        tolerance_samples=1_600,
    )
    review = verify_exact_export_events(
        [event], transient_result=wave, movement_results=[]
    )
    assert review["status"] == "needs-human-judgment"
    assert review["listeningWindows"][0]["eventId"] == "card"


def test_event_identity_owns_lifecycle_audio_effect_order_gain_and_priority() -> None:
    event = apply_event_role_defaults(
        {
            "eventId": "insert-7",
            "role": "overlay-video",
            "programFrame": 120,
            "visibleRange": {"startFrame": 120, "endFrameExclusive": 240},
            "sourceRange": {"startFrame": 12, "endFrameExclusive": 132},
            "sourceRef": "insert.mov",
            "entryEffectIds": ["rise", "impact"],
            "orderedMultiEffect": True,
            "audio": {"gainDb": -3.0, "priority": 40},
        }
    )
    assert event["eventId"] == "insert-7"
    assert event["visibleRange"] == {
        "startFrame": 120,
        "endFrameExclusive": 240,
    }
    assert event["entryEffectIds"] == ["rise", "impact"]
    assert event["audio"] == {
        "gainDb": -3.0,
        "priority": 40,
        "retainSourceAudio": True,
    }
    assert event["exitEffectIds"] == []
    assert event["exitAudioEnabled"] is False

    with pytest.raises(TrackError, match="main-scene"):
        apply_event_role_defaults(
            {
                "eventId": "main-1",
                "role": "main-scene",
                "entryEffectIds": ["automatic-pop"],
            }
        )
