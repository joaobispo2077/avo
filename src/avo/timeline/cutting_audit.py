"""Enumerate all canonical joins without treating duration as deletion evidence."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from .contracts import ContractError, content_hash
from .cutting_contracts import validate_source_range
from .lineage import validate_cmap_snapshot


def _source_range(segment: dict[str, Any]) -> dict[str, Any]:
    start, end = segment["in"], segment["out"]
    if start["timebase"] != end["timebase"]:
        raise ContractError(
            "cutting audit requires one exact source timebase per interval"
        )
    return validate_source_range(
        {
            "sourceId": segment["sourceId"],
            "startTicks": start["ticks"],
            "endTicksExclusive": end["ticks"],
            "timebase": start["timebase"],
        }
    )


def _time(value: int, timebase: dict[str, int]) -> Fraction:
    return Fraction(value * timebase["num"], timebase["den"])


def _frame(value: Fraction, fps: Fraction) -> int:
    exact = value * fps
    return (2 * exact.numerator + exact.denominator) // (2 * exact.denominator)


def _join_flags(left: dict, right: dict) -> list[str]:
    flags = []
    if left["sourceId"] != right["sourceId"]:
        flags.append("source-switch")
    else:
        previous = _time(left["endTicksExclusive"], left["timebase"])
        following = _time(right["startTicks"], right["timebase"])
        if previous < following:
            flags.append("source-discontinuity")
        elif previous > following:
            flags.append("source-overlap")
    for label, interval in (("left", left), ("right", right)):
        duration = _time(
            interval["endTicksExclusive"] - interval["startTicks"], interval["timebase"]
        )
        if duration < 1:
            flags.append(f"short-{label}-island")
    return flags


def audit_joins(
    snapshot: dict[str, Any], frame_rate: dict[str, int]
) -> list[dict[str, Any]]:
    """Return every inherited/new join and source-local structural alerts.

    A subsecond island is only a search flag. Legitimate short speech and inserts
    require the same source/context inspection as any other selection.
    """
    validate_cmap_snapshot(snapshot)
    if any(
        isinstance(frame_rate.get(key), bool)
        or not isinstance(frame_rate.get(key), int)
        or frame_rate[key] <= 0
        for key in ("num", "den")
    ):
        raise ContractError("cutting audit requires a positive rational frame rate")
    fps = Fraction(frame_rate["num"], frame_rate["den"])
    segments = snapshot["segments"]
    ranges = [_source_range(segment) for segment in segments]
    fingerprints = {
        source["sourceId"]: source["fingerprint"]["sha256"]
        for source in snapshot["sources"]
    }
    elapsed = Fraction(0)
    joins = []
    for index, interval in enumerate(ranges):
        if index:
            left = ranges[index - 1]
            identity = {
                "left": left,
                "right": interval,
                "leftFingerprint": fingerprints[left["sourceId"]],
                "rightFingerprint": fingerprints[interval["sourceId"]],
            }
            joins.append(
                {
                    "joinId": "join-" + content_hash(identity)[:24],
                    "leftSegmentId": segments[index - 1]["segmentId"],
                    "rightSegmentId": segments[index]["segmentId"],
                    "programFrame": _frame(elapsed, fps),
                    "leftSourceRange": left,
                    "rightSourceRange": interval,
                    "flags": _join_flags(left, interval),
                    "disposition": "needs-review",
                    "deletionAuthorized": False,
                }
            )
        elapsed += _time(
            interval["endTicksExclusive"] - interval["startTicks"], interval["timebase"]
        )
    return joins
