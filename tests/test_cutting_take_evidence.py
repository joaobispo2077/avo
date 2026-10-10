from avo.timeline.cutting_retakes import classify_take, group_retakes, select_retake
from test_cutting_retakes import evidence, take


def test_clearer_earlier_take_wins_and_source_order_breaks_equal_quality():
    group = group_retakes(
        [take("a", "a ideia central", 0), take("b", "a ideia central", 200)]
    )[0]
    checks = evidence("a", "b")
    checks["perTake"]["b"]["intelligibility"] = 0.6
    assert select_retake(group, checks)["selectedTakeId"] == "a"
    assert select_retake(group, evidence("a", "b"))["selectedTakeId"] == "a"


def test_better_picture_cannot_override_unintelligible_speech():
    group = group_retakes(
        [take("a", "a ideia central", 0), take("b", "a ideia central", 200)]
    )[0]
    checks = evidence("a", "b")
    checks["perTake"]["b"].update(intelligible=False, visualUsability=1)
    assert select_retake(group, checks)["selectedTakeId"] == "a"


def test_unknown_or_conflicting_evidence_never_authorizes_replacement():
    group = group_retakes([take("a", "a ideia", 0), take("b", "a ideia", 200)])[0]
    assert select_retake(group, {"confidence": 1})["action"] == "needs-review"
    assert select_retake(group, {**evidence("a", "b"), "conflict": True})[
        "requiresHuman"
    ]
    checks = evidence("a", "b")
    for item in checks["perTake"].values():
        item["acousticComplete"] = None
    assert select_retake(group, checks)["selectedTakeId"] is None


def test_accent_is_not_an_unclear_delivery_classification():
    result = classify_take(take("a", "a minha opinião", 0, accent="regional"))
    assert "unclear-delivery" not in result["categories"]


def test_missing_relevant_visual_evidence_requires_review():
    group = group_retakes([take("a", "a ideia", 0), take("b", "a ideia", 200)])[0]
    checks = evidence("a", "b")
    checks["perTake"]["a"].pop("visualUsability")
    checks["perTake"]["b"].pop("visualUsability")
    assert select_retake(group, checks)["requiresHuman"] is True


def test_fractional_ticks_and_nonfinite_quality_cannot_automatically_select():
    group = group_retakes([take("a", "a ideia", 0), take("b", "a ideia", 200)])[0]
    group["attempts"][0]["sourceRange"]["startTicks"] = 0.5
    assert select_retake(group, evidence("a", "b"))["requiresHuman"] is True
    group = group_retakes([take("a", "a ideia", 0), take("b", "a ideia", 200)])[0]
    checks = evidence("a", "b")
    checks["perTake"]["a"]["intelligibility"] = float("nan")
    assert select_retake(group, checks)["requiresHuman"] is True
