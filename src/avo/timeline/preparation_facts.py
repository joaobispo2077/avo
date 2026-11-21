"""Combine only measured source windows; selection never certifies other time."""

from .cutting_contracts import source_interval
from .preparation import (
    _analysis_facts,
    _has_coverage_facts,
    _measured_interval,
    _measured_windows,
    _union,
)


def _measurements(analysis, bounds):
    try:
        facts = _analysis_facts(analysis)
        coverage = facts["coverage"] or {}
        if coverage.get("observed") is not True or not _has_coverage_facts(
            facts, {"routing": facts["routing"] or {}}
        ):
            return [], []
        measured = _measured_windows(coverage, bounds)
        activity = _union(
            _measured_interval(row, bounds, measured) for row in facts["vad"]
        )
        return measured, activity
    except (ValueError, TypeError, KeyError, AttributeError):
        return [], []


def _rows(intervals):
    return [{"start": float(first), "end": float(end)} for first, end in intervals]


def _measured_pause(row, source_id, measured):
    try:
        identity, first, end = source_interval(row["sourceRange"])
        return identity == source_id and any(
            start <= first < end <= finish for start, finish in measured
        )
    except (ValueError, TypeError, KeyError):
        return False


def merge_selected_measurements(analysis, chosen, bounds):
    """Mutate a private derived view, retaining original/result provenance elsewhere."""
    interval = analysis["preprocessing"]["sourceRange"]
    identity, first, end = source_interval(interval)
    previous, previous_activity = _measurements(analysis, (first, end))
    incoming, incoming_activity = _measurements(chosen, bounds)
    if not incoming:
        return False
    measured = _union([*previous, *incoming])
    if len(measured) > 128:
        raise ValueError("Selected measured coverage exceeds its window budget")
    analysis.update(
        status="pass",
        coverage={"observed": True, "intervals": _rows(measured)},
        vad=_rows(_union([*previous_activity, *incoming_activity])),
        pauseCandidates=[
            row
            for row in analysis.get("pauseCandidates", [])
            if _measured_pause(row, identity, previous)
        ],
    )
    return True
