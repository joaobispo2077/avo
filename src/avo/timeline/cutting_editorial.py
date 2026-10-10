"""Substantive shortening suggestions remain separate from execution cleanup."""

from copy import deepcopy

from .contracts import ContractError
from .cutting_contracts import source_interval


def _range(unit: dict):
    try:
        return source_interval(unit.get("sourceRange") or {})
    except (ContractError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _duration_ms(unit: dict) -> int:
    interval = _range(unit)
    if interval is None:
        return 0
    duration = (interval[2] - interval[1]) * 1000
    return (2 * duration.numerator + duration.denominator) // (2 * duration.denominator)


def _overlapping_ids(units: list[dict]) -> set[str]:
    intervals = [(unit["unitId"], _range(unit)) for unit in units]
    conflicts = set()
    for index, (left_id, left) in enumerate(intervals):
        for right_id, right in intervals[index + 1 :]:
            if left is None or right is None:
                continue
            if left[0] == right[0] and max(left[1], right[1]) < min(left[2], right[2]):
                conflicts.update((left_id, right_id))
    return conflicts


def _preservation_reasons(unit: dict, dependents: dict) -> list[str]:
    reasons = []
    for flag in ("central", "uniqueQualification", "meaningfulExample", "protected"):
        if unit.get(flag):
            reasons.append(flag)
    if unit.get("complete") is not True:
        reasons.append("incomplete-unit")
    if not unit.get("rationale") or not (
        unit.get("redundantTo") or unit.get("tangent") is True
    ):
        reasons.append("unsupported-shortening-rationale")
    if dependents.get(unit["unitId"]):
        reasons.append("required-by-retained-unit")
    return reasons


def _dependencies(units: list[dict]) -> dict:
    dependents: dict[str, list[str]] = {}
    for unit in units:
        for parent in unit.get("dependsOn", []):
            dependents.setdefault(parent, []).append(unit["unitId"])
    return dependents


def _candidates(units: list[dict], dependents: dict, overlaps: set) -> list[dict]:
    candidates = []
    for unit in units:
        duration = _duration_ms(unit)
        reasons = _preservation_reasons(unit, dependents)
        if unit["unitId"] in overlaps:
            reasons.append("overlapping-source-unit")
        if not duration:
            reasons.append("missing-source-duration")
        candidates.append(
            {
                "unitId": unit["unitId"],
                "sectionId": unit.get("sectionId"),
                "sourceRange": deepcopy(unit.get("sourceRange")),
                "rationale": unit.get("rationale"),
                "dependencies": list(unit.get("dependsOn", [])),
                "requiredBy": dependents.get(unit["unitId"], []),
                "eligible": not reasons,
                "preservationReasons": reasons,
                "expectedSavingsMs": duration if not reasons else 0,
            }
        )
    return candidates


def propose_editorial_shortening(
    units: list[dict], *, current_duration_ms=None, target_duration_ms=None
) -> dict:
    if len({unit["unitId"] for unit in units}) != len(units):
        raise ValueError("editorial units require unique stable IDs")
    candidates = _candidates(units, _dependencies(units), _overlapping_ids(units))
    savings = sum(item["expectedSavingsMs"] for item in candidates)
    target_gap = None
    if current_duration_ms is not None and target_duration_ms is not None:
        target_gap = max(0, current_duration_ms - target_duration_ms - savings)
    return {
        "kind": "editorial-shortening",
        "candidates": candidates,
        "proposedSavingsMs": savings,
        "remainingTargetGapMs": target_gap,
        "requiresEditorialApproval": True,
        "applied": False,
    }
