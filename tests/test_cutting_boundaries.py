from avo.timeline.cutting_boundaries import propose_pause
from avo.timeline.cutting_policy import resolve_cutting_policy


def interval(start, end):
    return {
        "sourceId": "dialogue",
        "startTicks": start,
        "endTicksExclusive": end,
        "timebase": {"num": 1, "den": 1000},
    }


def policy():
    return resolve_cutting_policy(
        project_settings={
            "enabled": True,
            "family": "analysis-review",
            "language": "pt",
        }
    )


def evidence():
    return {
        "quietRanges": [interval(1000, 2000)],
        "adjacentWords": {"before": "palavra", "after": "outra"},
        "wordEdges": {
            "beforeEndTicks": 1000,
            "afterStartTicks": 2000,
            "status": "observed",
        },
        "context": {"dispensable": True, "intentionalPause": False},
        "acousticObserved": True,
    }


def test_safe_pause_preserves_word_guards_and_target():
    result = propose_pause(interval(1000, 2000), policy(), evidence())
    assert result["disposition"] == "shorten"
    assert result["removeRange"] == interval(1180, 1730)
    assert result["retainedMs"] == 450


def test_word_omitted_by_transcript_prevents_silence_cut():
    data = evidence()
    data["speechRanges"] = [interval(1200, 1400)]
    result = propose_pause(interval(1000, 2000), policy(), data)
    assert result["disposition"] == "needs-review"
    assert "removeRange" not in result


def test_missing_alignment_is_not_an_automatic_decision():
    data = evidence()
    data["wordEdges"]["status"] = "interpolated"
    assert (
        propose_pause(interval(1000, 2000), policy(), data)["disposition"]
        == "needs-review"
    )


def test_protected_quiz_cannot_be_shortened():
    selected = resolve_cutting_policy(
        project_settings={"enabled": True, "family": "analysis-review"},
        protected_events=[{"eventId": "quiz", "sourceRange": interval(1200, 1600)}],
    )
    assert (
        propose_pause(interval(1000, 2000), selected, evidence())["disposition"]
        == "keep"
    )


def test_actual_word_tail_outside_estimated_gap_prevents_cut():
    data = evidence()
    data["wordEdges"]["beforeEndTicks"] = 1300
    assert (
        propose_pause(interval(1000, 2000), policy(), data)["disposition"]
        == "needs-review"
    )


def test_frame_quantization_increases_retention_not_word_loss():
    result = propose_pause(
        interval(1000, 2000), policy(), evidence(), frame_rate={"num": 30, "den": 1}
    )
    assert result["removeRange"]["startTicks"] >= 1180
    assert result["removeRange"]["endTicksExclusive"] <= 1730
    assert result["retainedMs"] >= 450
