import pytest

from avo.timeline.cutting_evaluation import evaluate_cutting, proportion_interval


def case(identity, **changes):
    return {
        "caseId": identity,
        "language": "pt-BR",
        "family": "analysis-review",
        "intensity": "balanced",
        "category": "excess-silence",
        "split": "held-out",
        "annotationStatus": "adjudicated",
        "safeUnambiguous": True,
        "autoApplied": True,
        "accepted": True,
        "severeViolation": False,
        **changes,
    }


def test_every_automatic_decision_is_in_precision_denominator():
    records = [case(str(index)) for index in range(200)]
    records[-1].update(accepted=False, safeUnambiguous=False)
    report = evaluate_cutting(records)
    precision = report["languages"]["pt-BR"]["precision"]
    assert precision["numerator"] == 199
    assert precision["denominator"] == 200
    assert precision["value"] == 0.995
    assert precision["passes"] is True
    assert report["status"] == "insufficient-evidence"


def test_safe_resolution_cannot_be_satisfied_by_abstaining():
    report = evaluate_cutting(
        [case(str(index), autoApplied=False) for index in range(200)]
    )
    assert report["languages"]["pt-BR"]["safeResolution"]["value"] == 0
    assert report["languages"]["pt-BR"]["safeResolution"]["passes"] is False


def test_unknown_annotations_and_calibration_do_not_become_validation():
    report = evaluate_cutting(
        [
            case("unknown", annotationStatus="unknown", accepted=None),
            case("cal", split="calibration"),
        ]
    )
    assert report["calibrationExcluded"] == 1
    assert report["unknownAnnotations"] == 1
    assert report["status"] == "insufficient-evidence"
    assert report["languages"]["en"]["precision"]["value"] is None


def test_zero_severe_violations_is_an_independent_blocker():
    report = evaluate_cutting([case("unsafe", severeViolation=True)])
    assert report["status"] == "fail"
    assert report["severeViolations"] == 1


def test_binomial_interval_reports_uncertainty_without_inventing_samples():
    assert proportion_interval(0, 0) is None
    lower, upper = proportion_interval(200, 200)
    assert 0.98 < lower < 1
    assert upper == pytest.approx(1)


def test_technical_rework_is_separate_from_creative_requests():
    pairs = [
        {
            "pairId": str(index),
            "language": "pt-BR",
            "sameBrief": True,
            "baselineReviewComplete": True,
            "currentReviewComplete": True,
            "baselineCorrections": 10,
            "newCorrections": 4,
            "creativeRequests": 99,
        }
        for index in range(3)
    ]
    report = evaluate_cutting([], pairs=pairs)
    assert report["languages"]["pt-BR"]["correctionReduction"]["value"] == 0.6
    assert report["languages"]["pt-BR"]["correctionReduction"]["passes"] is True
    assert report["languages"]["en"]["correctionReduction"]["value"] is None


def test_calibration_leakage_is_rejected():
    with pytest.raises(ValueError, match="calibration"):
        evaluate_cutting([case("same", split="calibration"), case("same")])
