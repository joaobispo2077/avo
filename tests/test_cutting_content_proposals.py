from avo.timeline.cutting_content_proposals import editorial_proposal


def fixture():
    clock = {"num": 1, "den": 1000}
    interval = {
        "sourceId": "s",
        "startTicks": 100,
        "endTicksExclusive": 400,
        "timebase": clock,
    }
    snapshot = {
        "sources": [{"sourceId": "s", "fingerprint": {"sha256": "a" * 64}}],
        "segments": [
            {
                "segmentId": "seg",
                "sourceId": "s",
                "in": {"ticks": 0, "timebase": clock},
                "out": {"ticks": 1000, "timebase": clock},
            }
        ],
    }
    request = {
        "targetDurationMs": 500,
        "editorialUnits": [
            {
                "unitId": "u",
                "sourceRange": interval,
                "complete": True,
                "tangent": True,
                "rationale": "Already explained",
                "protected": False,
            }
        ],
    }
    return snapshot, request


def test_content_removal_is_separate_and_requires_editorial_approval():
    snapshot, request = fixture()
    result, occurrences, edits = editorial_proposal(snapshot, request, ())
    assert result["remainingTargetGapMs"] == 200
    assert result["requiresEditorialApproval"] is True
    assert edits[0]["editorialApprovalRequired"] is True
    assert edits[0]["segmentId"] == "seg"
    assert occurrences[0]["disposition"] == "needs-review"


def test_hard_source_protection_overrides_editorial_request():
    snapshot, request = fixture()
    protections = [
        {"eventId": "quiz", "sourceRange": request["editorialUnits"][0]["sourceRange"]}
    ]
    result, occurrences, edits = editorial_proposal(snapshot, request, protections)
    assert edits == []
    assert result["proposedSavingsMs"] == 0
    assert occurrences[0]["protections"] == ["quiz"]


def test_editorial_unit_must_be_wholly_in_current_source_selection():
    snapshot, request = fixture()
    request["editorialUnits"][0]["sourceRange"]["endTicksExclusive"] = 2000
    result, _, edits = editorial_proposal(snapshot, request, ())
    assert edits == []
    assert not result["candidates"][0]["eligible"]
