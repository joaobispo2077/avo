"""Bind editorial suggestions to current whole source selections, never apply them."""

from copy import deepcopy

from .cutting_contracts import occurrence_id, source_interval
from .cutting_editorial import propose_editorial_shortening


def _selected_range(segment):
    return {
        "sourceId": segment["sourceId"],
        "startTicks": segment["in"]["ticks"],
        "endTicksExclusive": segment["out"]["ticks"],
        "timebase": segment["in"]["timebase"],
    }


def _owner(interval, segments):
    source, start, end = source_interval(interval)
    for segment in segments:
        other, first, last = source_interval(_selected_range(segment))
        if (
            source == other
            and first <= start < end <= last
            and interval["timebase"] == segment["in"]["timebase"]
        ):
            return segment
    return None


def _protected(interval, protections):
    source, start, end = source_interval(interval)
    found = []
    for protected in protections:
        other, first, last = source_interval(protected["sourceRange"])
        if source == other and max(start, first) < min(end, last):
            found.append(protected["eventId"])
    return sorted(found)


def _prepared(snapshot, request, protections):
    units, owners, protected_ids = deepcopy(request.get("editorialUnits", [])), {}, {}
    for unit in units:
        interval = unit["sourceRange"]
        owner = _owner(interval, snapshot["segments"])
        protected_ids[unit["unitId"]] = _protected(interval, protections)
        owners[unit["unitId"]] = owner
        unit["protected"] = bool(
            unit.get("protected") or protected_ids[unit["unitId"]] or owner is None
        )
    return units, owners, protected_ids


def editorial_proposal(snapshot: dict, request: dict, protections=()):
    """Return contentReduction, review occurrences and separately approval-gated edits."""
    units, owners, protected_ids = _prepared(snapshot, request, protections)
    duration = sum(
        (
            source_interval(_selected_range(segment))[2]
            - source_interval(_selected_range(segment))[1]
        )
        * 1000
        for segment in snapshot["segments"]
    )
    report = propose_editorial_shortening(
        units,
        current_duration_ms=round(duration),
        target_duration_ms=request.get("targetDurationMs"),
    )
    sources = {source["sourceId"]: source for source in snapshot["sources"]}
    occurrences, edits = [], []
    for candidate in report["candidates"]:
        source = sources[candidate["sourceRange"]["sourceId"]]
        identity = occurrence_id(
            source["fingerprint"]["sha256"],
            source["sourceId"],
            {"editorialUnit": candidate["unitId"]},
        )
        occurrences.append(
            {
                "occurrenceId": identity,
                "sourceRange": deepcopy(candidate["sourceRange"]),
                "categories": ["content-reduction"],
                "disposition": "needs-review",
                "reasons": candidate["preservationReasons"] or [candidate["rationale"]],
                "protections": protected_ids[candidate["unitId"]],
                "editorialApprovalRequired": True,
            }
        )
        if candidate["eligible"]:
            edits.append(
                {
                    "occurrenceId": identity,
                    "segmentId": owners[candidate["unitId"]]["segmentId"],
                    "removeRange": deepcopy(candidate["sourceRange"]),
                    "editorialApprovalRequired": True,
                }
            )
    return report, occurrences, edits
