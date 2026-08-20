"""Pure raw-source ↔ CMap-output mapping using integer ticks."""

from __future__ import annotations

from fractions import Fraction
from typing import Any


class MappingError(ValueError):
    pass


def _time(value: dict[str, Any]) -> Fraction:
    base = value["timebase"]
    return Fraction(int(value["ticks"]) * int(base["num"]), int(base["den"]))


def _output_base(snapshot: dict[str, Any]) -> Fraction:
    segments = snapshot.get("segments") or []
    if not segments:
        raise MappingError("CMap has no segments")
    base = segments[0]["in"]["timebase"]
    return Fraction(int(base["num"]), int(base["den"]))


def _to_output_ticks(seconds: Fraction, base: Fraction) -> int:
    ticks = seconds / base
    if ticks.denominator != 1:
        raise MappingError(
            "time cannot be represented exactly in the CMap output timebase"
        )
    return ticks.numerator


def cmap_output_duration(snapshot: dict[str, Any]) -> int:
    base = _output_base(snapshot)
    duration = sum(
        (_time(item["out"]) - _time(item["in"]) for item in snapshot["segments"]),
        Fraction(),
    )
    return _to_output_ticks(duration, base)


def cmap_raw_to_output(
    snapshot: dict[str, Any],
    source_id: str,
    raw_ticks: int,
    *,
    raw_timebase: dict[str, int] | None = None,
) -> int | None:
    base = _output_base(snapshot)
    offset = Fraction()
    for segment in snapshot.get("segments") or []:
        start = _time(segment["in"])
        end = _time(segment["out"])
        if segment["sourceId"] == source_id:
            source_base = raw_timebase or segment["in"]["timebase"]
            point = Fraction(
                raw_ticks * int(source_base["num"]), int(source_base["den"])
            )
            if start <= point <= end:
                return _to_output_ticks(offset + point - start, base)
        offset += end - start
    return None


def cmap_output_to_raw(
    snapshot: dict[str, Any], output_ticks: int
) -> tuple[str, int] | None:
    base = _output_base(snapshot)
    point = output_ticks * base
    offset = Fraction()
    segments = snapshot.get("segments") or []
    for index, segment in enumerate(segments):
        start = _time(segment["in"])
        end = _time(segment["out"])
        duration = end - start
        boundary = offset + duration
        is_last = index == len(segments) - 1
        if point < boundary or (is_last and point <= boundary):
            if point < offset:
                return None
            source_point = start + point - offset
            source_base = Fraction(
                int(segment["in"]["timebase"]["num"]),
                int(segment["in"]["timebase"]["den"]),
            )
            ticks = source_point / source_base
            if ticks.denominator != 1:
                raise MappingError("mapped raw time is not integral in source timebase")
            return str(segment["sourceId"]), ticks.numerator
        offset = boundary
    return None


def legacy_output_duration(ranges: list[Any]) -> float:
    """Compatibility adapter for legacy float-second EDL ranges."""
    return sum(float(item.end) - float(item.start) for item in ranges)


def legacy_source_to_output(
    ranges: list[Any], source_time: float, *, source: str | None = None
) -> float | None:
    ids = {str(item.source) for item in ranges}
    if source is None:
        if len(ids) > 1:
            raise ValueError("multi-source EDL requires source/anchor_source")
        source = next(iter(ids), None)
    offset = 0.0
    for item in ranges:
        if (
            str(item.source) == source
            and float(item.start) - 1e-6 <= source_time <= float(item.end) + 1e-6
        ):
            return offset + source_time - float(item.start)
        offset += float(item.end) - float(item.start)
    return None


def legacy_output_to_source_anchor(
    ranges: list[Any], output_time: float
) -> tuple[str, float] | None:
    offset = 0.0
    for index, item in enumerate(ranges):
        duration = float(item.end) - float(item.start)
        end = offset + duration
        is_last = index == len(ranges) - 1
        if output_time < end - 1e-6 or (is_last and output_time <= end + 1e-6):
            if output_time < offset - 1e-6:
                return None
            return str(item.source), float(item.start) + output_time - offset
        offset = end
    return None


def classify_cue_rebase(
    old_ranges: list[tuple[int, int]] | list[list[int]],
    new_ranges: list[tuple[int, int]] | list[list[int]],
) -> str:
    if not old_ranges:
        return "unsupported"
    if not new_ranges:
        return "removed"
    if len(old_ranges) == 1 and len(new_ranges) > 1:
        old_duration = old_ranges[0][1] - old_ranges[0][0]
        covered = sum(end - start for start, end in new_ranges)
        if covered < old_duration:
            return "split"
        return "ambiguous"
    if len(old_ranges) != len(new_ranges):
        return "ambiguous"
    if list(map(tuple, old_ranges)) == list(map(tuple, new_ranges)):
        return "preserved"
    old_durations = [end - start for start, end in old_ranges]
    new_durations = [end - start for start, end in new_ranges]
    if old_durations == new_durations:
        shifts = [new[0] - old[0] for old, new in zip(old_ranges, new_ranges)]
        if len(set(shifts)) == 1:
            return "shifted"
    return "ambiguous"
