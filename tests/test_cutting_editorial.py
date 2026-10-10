from avo.timeline.cutting_editorial import propose_editorial_shortening


def unit(identity, **extra):
    return {
        "unitId": identity,
        "sectionId": "argument",
        "complete": True,
        "sourceRange": {
            "sourceId": "s",
            "startTicks": 0,
            "endTicksExclusive": 1000,
            "timebase": {"num": 1, "den": 1000},
        },
        "rationale": "duplicates the previous complete example",
        "redundantTo": "core",
        **extra,
    }


def test_shortening_is_separate_proposal_without_apply_permission():
    report = propose_editorial_shortening(
        [unit("repeat")], current_duration_ms=5000, target_duration_ms=3000
    )
    assert report["kind"] == "editorial-shortening"
    assert report["requiresEditorialApproval"] is True
    assert report["proposedSavingsMs"] == 1000
    assert report["remainingTargetGapMs"] == 1000
    assert report["applied"] is False


def test_unique_qualifications_examples_and_dependencies_are_preserved():
    report = propose_editorial_shortening(
        [
            unit("qualification", uniqueQualification=True),
            unit("example", meaningfulExample=True),
            unit("quiz", protected=True),
            unit("premise"),
            unit("payoff", dependsOn=["premise"]),
        ],
        current_duration_ms=10000,
        target_duration_ms=1000,
    )
    blocked = {item["unitId"] for item in report["candidates"] if not item["eligible"]}
    assert {"qualification", "example", "quiz", "premise"} <= blocked
    assert report["remainingTargetGapMs"] > 0


def test_incomplete_unit_or_unknown_reason_is_not_proposed_for_removal():
    report = propose_editorial_shortening(
        [unit("incomplete", complete=False), unit("unknown", rationale=None)]
    )
    assert report["proposedSavingsMs"] == 0


def test_overlapping_proposals_do_not_double_count_savings():
    report = propose_editorial_shortening([unit("a"), unit("b")])
    assert report["proposedSavingsMs"] == 0
    assert all(not candidate["eligible"] for candidate in report["candidates"])
