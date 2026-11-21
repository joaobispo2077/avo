"""Spoken notes retain verbatim source evidence and separate interpretation."""

import pytest

from avo.timeline.preparation_notes import detect_spoken_notes

SOURCE = {
    "sourceId": "camera-a",
    "startTicks": 0,
    "endTicksExclusive": 4000,
    "timebase": {"num": 1, "den": 1000},
}
POLICY = {
    "enabled": True,
    "language": "en",
    "openingPhrase": "Editor note",
    "closingPhrase": "End note",
}
TARGETS = [
    {"phrase": "Opening graphic", "stage": "motion", "targetId": "opening-title"}
]


def transcript(text, *, language="en"):
    return {
        "language": language,
        "alignment": {"status": "pass"},
        "words": [
            {
                "text": part,
                "start": offset / 10,
                "end": (offset + 1) / 10,
                "eligibleEdge": True,
            }
            for offset, part in enumerate(text.split())
        ],
    }


def test_complete_literal_note_has_exact_original_range_and_proposed_target():
    analysis = transcript(
        "Before. Editor note: Opening graphic then slow down! End note. After."
    )
    result = detect_spoken_notes(analysis, SOURCE, policy=POLICY, targets=TARGETS)
    (note,) = result["notes"]
    assert note["literal"] == "Editor note: Opening graphic then slow down! End note."
    assert note["body"] == "Opening graphic then slow down!"
    assert (
        note["sourceRange"]["startTicks"],
        note["sourceRange"]["endTicksExclusive"],
    ) == (100, 1000)
    assert note["review"] == "required"
    assert note["status"] == "candidate"
    assert note["interpretation"] == {
        "intent": "Opening graphic then slow down!",
        "stage": "motion",
        "targetId": "opening-title",
        "confidence": "matched-convention",
    }


@pytest.mark.parametrize(
    ("text", "issue"),
    [
        (
            'I said "Editor note Opening graphic cut End note" on camera.',
            "quoted-delimiter",
        ),
        ("Editorr note Opening graphic move. End note.", "fuzzy-delimiter"),
        (
            "Editor note Opening graphic Editor note continue End note End note",
            "nested-delimiter",
        ),
        ("Editor note Opening graphic keep going", "missing-closure"),
        ("Editor note Unknown context End note", "target-unresolved"),
    ],
)
def test_ambiguous_or_unclosed_notes_remain_unresolved(text, issue):
    result = detect_spoken_notes(
        transcript(text), SOURCE, policy=POLICY, targets=TARGETS
    )
    (note,) = result["notes"]
    assert note["status"] == "unresolved"
    assert issue in note["issues"]
    if issue == "missing-closure":
        assert note["sourceRange"] is None


def test_missing_convention_and_other_transcript_languages_do_not_match():
    row = transcript("Editor note Opening graphic End note", language="de")
    assert (
        detect_spoken_notes(row, SOURCE, policy={"enabled": False}, targets=TARGETS)[
            "status"
        ]
        == "disabled"
    )
    response = detect_spoken_notes(row, SOURCE, policy=POLICY, targets=TARGETS)
    assert response["status"] == "unavailable"
    assert response["notes"] == []
