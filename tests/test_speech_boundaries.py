from __future__ import annotations

from avo.timeline.review_runner import compare_protected_boundaries

SOURCE = {
    "words": [
        {"word": "do", "start": 0.0, "end": 0.2},
        {"word": "not", "start": 0.2, "end": 0.4},
        {"word": "cut", "start": 0.4, "end": 0.7},
    ]
}


def test_complete_protected_phrase_and_tactile_event_pass() -> None:
    result = compare_protected_boundaries(
        SOURCE,
        SOURCE,
        protected_boundaries=[
            {
                "boundaryId": "phrase-1",
                "kind": "phrase",
                "text": "do not cut",
                "start": 0.0,
                "end": 0.7,
            },
            {"boundaryId": "click-1", "kind": "tactile", "start": 0.69, "end": 0.72},
        ],
        acoustic_checks={
            "phrase-1": {"confidence": 0.99, "complete": True},
            "click-1": {"confidence": 0.95, "complete": True},
        },
    )
    assert result["status"] == "pass"
    assert result["findings"] == []


def test_missing_word_is_a_regression_and_ambiguous_acoustics_need_human() -> None:
    candidate = {"words": [SOURCE["words"][0], SOURCE["words"][2]]}
    result = compare_protected_boundaries(
        SOURCE,
        candidate,
        protected_boundaries=[
            {
                "boundaryId": "phrase-1",
                "kind": "phrase",
                "text": "do not cut",
                "start": 0.0,
                "end": 0.7,
            },
            {"boundaryId": "breath-1", "kind": "cadence", "start": 0.7, "end": 0.9},
        ],
        acoustic_checks={
            "phrase-1": {"confidence": 0.98, "complete": False},
            "breath-1": {"confidence": 0.25, "complete": None},
        },
    )
    assert result["status"] == "fail"
    assert {item["code"] for item in result["findings"]} == {
        "protected-speech-regression",
        "acoustic-boundary-needs-human",
    }
