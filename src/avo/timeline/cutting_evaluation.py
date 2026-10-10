"""Measured cutting outcomes; absent or sparse evidence cannot validate a release."""

import math

from .cutting_profiles import FAMILIES, INTENSITIES

_LANGUAGES = ("pt-BR", "en")


def proportion_interval(successes: int, total: int) -> tuple[float, float] | None:
    """Wilson 95% binomial interval, reported separately from point targets."""
    if total == 0:
        return None
    if not 0 <= successes <= total:
        raise ValueError("binomial counts must satisfy zero <= successes <= total")
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = (
        z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    )
    return max(0, center - radius), min(1, center + radius)


def _accepted(case: dict) -> bool:
    return all(
        (
            case.get("accepted") is True,
            case.get("annotationStatus") == "adjudicated",
            case.get("severeViolation") is not True,
        )
    )


def _metric(
    numerator: int, denominator: int, threshold: float, minimum: int = 200
) -> dict:
    value = numerator / denominator if denominator else None
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "confidenceInterval95": proportion_interval(numerator, denominator),
        "minimumCount": minimum,
        "passes": value >= threshold if denominator >= minimum else None,
    }


def _decision_metrics(cases: list[dict], minimum=200) -> dict:
    automatic = [case for case in cases if case.get("autoApplied") is True]
    safe = [
        case
        for case in cases
        if case.get("safeUnambiguous") is True
        and case.get("annotationStatus") == "adjudicated"
    ]
    return {
        "precision": _metric(
            sum(_accepted(case) for case in automatic), len(automatic), 0.98, minimum
        ),
        "safeResolution": _metric(
            sum(case.get("autoApplied") is True and _accepted(case) for case in safe),
            len(safe),
            0.8,
            minimum,
        ),
    }


def _strata(cases: list[dict], key: str) -> dict:
    values = {str(case.get(key) or "unknown") for case in cases}
    return {
        value: {"caseCount": len(selected), **_decision_metrics(selected)}
        for value in sorted(values)
        for selected in [
            [case for case in cases if str(case.get(key) or "unknown") == value]
        ]
    }


def _paired_reduction(pairs: list[dict]) -> dict:
    usable = [
        pair
        for pair in pairs
        if all(
            (
                pair.get("sameBrief") is True,
                pair.get("baselineReviewComplete") is True,
                pair.get("currentReviewComplete") is True,
            )
        )
    ]
    baseline = sum(pair["baselineCorrections"] for pair in usable)
    current = sum(pair["newCorrections"] for pair in usable)
    value = (baseline - current) / baseline if baseline else None
    return {
        "pairedPrograms": len(usable),
        "baselineCorrections": baseline if usable else None,
        "currentCorrections": current if usable else None,
        "value": value,
        "passes": value >= 0.5 if len(usable) >= 3 and value is not None else None,
    }


def _partition(records: list[dict]) -> tuple[list[dict], int]:
    held_out, calibration = [], []
    for case in records:
        if case.get("split") == "calibration":
            calibration.append(case)
        elif case.get("split") == "held-out":
            held_out.append(case)
        else:
            raise ValueError(
                "evaluation requires an explicit calibration or held-out split"
            )
    calibration_ids = {case["caseId"] for case in calibration}
    if calibration_ids & {case["caseId"] for case in held_out}:
        raise ValueError("calibration cases cannot appear in held-out evaluation")
    if len({case["caseId"] for case in held_out}) != len(held_out):
        raise ValueError("held-out case IDs must be unique")
    return held_out, len(calibration)


def _profile_coverage(cases: list[dict]) -> dict:
    counts = {
        f"{family}/{intensity}": sum(
            case.get("family") == family and case.get("intensity") == intensity
            for case in cases
        )
        for family in FAMILIES
        for intensity in INTENSITIES
    }
    return {
        "counts": counts,
        "missing": [key for key, count in counts.items() if not count],
    }


def _language_report(language: str, cases: list[dict], pairs: list[dict]) -> dict:
    selected = [case for case in cases if case.get("language") == language]
    return {
        **_decision_metrics(selected),
        "byCategory": _strata(selected, "category"),
        "byProfile": _strata(
            [
                {**case, "profile": f"{case.get('family')}/{case.get('intensity')}"}
                for case in selected
            ],
            "profile",
        ),
        "profileCoverage": _profile_coverage(selected),
        "correctionReduction": _paired_reduction(
            [pair for pair in pairs if pair.get("language") == language]
        ),
    }


def _status(languages: dict, severe: int, unknown: int) -> str:
    checks = [
        result[name]["passes"]
        for result in languages.values()
        for name in ("precision", "safeResolution", "correctionReduction")
    ]
    if severe or False in checks:
        return "fail"
    missing = any(result["profileCoverage"]["missing"] for result in languages.values())
    if unknown or None in checks or missing:
        return "insufficient-evidence"
    return "pass"


def evaluate_cutting(records: list[dict], *, pairs: list[dict] = ()) -> dict:
    """Compute per-language metrics without applying edits or certifying hearing."""
    cases, excluded = _partition(records)
    for pair in pairs:
        counts = (pair.get("baselineCorrections"), pair.get("newCorrections"))
        if not all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in counts
        ):
            raise ValueError("paired correction counts must be nonnegative integers")
    languages = {
        language: _language_report(language, cases, list(pairs))
        for language in _LANGUAGES
    }
    severe = sum(case.get("severeViolation") is True for case in cases)
    unknown = sum(case.get("annotationStatus") != "adjudicated" for case in cases)
    return {
        "languages": languages,
        "calibrationExcluded": excluded,
        "unknownAnnotations": unknown,
        "severeViolations": severe,
        "status": _status(languages, severe, unknown),
        "claims": "Annotated selection outcomes only; machine/text results are not human listening approval.",
    }
