from __future__ import annotations

from avo.timeline.vision_review import fuse_protected_event_evidence


def test_visible_action_fuses_with_transcript_and_waveform_without_overclaiming() -> (
    None
):
    speech = fuse_protected_event_evidence(
        event_id="speech-1",
        kind="speech",
        visual_status="fail",
        deterministic_status="fail",
    )
    assert speech["status"] == "corroborated"
    assert speech["severity"] == "blocking"
    tactile = fuse_protected_event_evidence(
        event_id="button-1",
        kind="tactile",
        visual_status="pass",
        deterministic_status="pass",
    )
    assert tactile["status"] == "pass"
    ambiguous = fuse_protected_event_evidence(
        event_id="button-2",
        kind="tactile",
        visual_status="fail",
        deterministic_status="pass",
    )
    assert ambiguous["status"] == "needs-human-judgment"
