"""Pure raw-source ↔ CMap-output mapping using integer ticks."""

from __future__ import annotations

from fractions import Fraction
from typing import Any


class MappingError(ValueError):
    pass


def _time(value: dict[str, Any]) -> Fraction:
    base = value["timebase"]
    return Fraction(int(value["ticks"]) * int(base["num"]), int(base["den"]))


def cmap_output_timebase(snapshot: dict[str, Any]) -> dict[str, int]:
    """Return the program clock without borrowing mutable snapshot evidence."""
    if snapshot.get("layoutMode") == "placed":
        base = snapshot["layout"]["programClock"]["timebase"]
    else:
        segments = snapshot.get("segments") or []
        if not segments:
            raise MappingError("CMap has no segments")
        base = segments[0]["in"]["timebase"]
    return {"num": int(base["num"]), "den": int(base["den"])}


def _output_base(snapshot: dict[str, Any]) -> Fraction:
    base = cmap_output_timebase(snapshot)
    return Fraction(int(base["num"]), int(base["den"]))


def _check_raw_clock(items, source_id, raw_timebase):
    if raw_timebase is not None:
        return
    clocks = {
        Fraction(item["in"]["timebase"]["num"], item["in"]["timebase"]["den"])
        for item in items
        if item["sourceId"] == source_id
    }
    if len(clocks) > 1:
        raise MappingError(
            "ambiguous raw source clock; supply raw_timebase or select a placement"
        )


def _to_output_ticks(seconds: Fraction, base: Fraction) -> int:
    ticks = seconds / base
    if ticks.denominator != 1:
        raise MappingError(
            "time cannot be represented exactly in the CMap output timebase"
        )
    return ticks.numerator


def cmap_output_duration(snapshot: dict[str, Any]) -> int:
    base = _output_base(snapshot)
    if snapshot.get("layoutMode") == "placed":
        return _to_output_ticks(_time(snapshot["layout"]["duration"]), base)
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
    placement_id: str | None = None,
    track_id: str | None = None,
) -> int | None:
    if snapshot.get("layoutMode") == "placed":
        return _placed_raw_to_output(
            snapshot, source_id, raw_ticks, raw_timebase, placement_id, track_id
        )
    base = _output_base(snapshot)
    _check_raw_clock(snapshot.get("segments") or [], source_id, raw_timebase)
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
    snapshot: dict[str, Any],
    output_ticks: int,
    *,
    placement_id: str | None = None,
    track_id: str | None = None,
) -> tuple[str, int] | None:
    if snapshot.get("layoutMode") == "placed":
        return _placed_output_to_raw(snapshot, output_ticks, placement_id, track_id)
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


def _one_mapping(values):
    if len(values) > 1:
        raise MappingError("ambiguous placed mapping; select a placement or track")
    return values[0] if values else None


def _placed_raw_to_output(
    snapshot, source_id, raw_ticks, raw_timebase, placement_id, track_id
):
    from .import_layout import active_placements

    selected = list(
        active_placements(snapshot, placement_id=placement_id, track_id=track_id)
    )
    _check_raw_clock(selected, source_id, raw_timebase)
    values = []
    for item in selected:
        if item["sourceId"] != source_id:
            continue
        clock = raw_timebase or item["in"]["timebase"]
        point = Fraction(raw_ticks * clock["num"], clock["den"])
        first, last = _time(item["in"]), _time(item["out"])
        if first <= point < last:
            offset = Fraction(0) if item["mediaKind"] == "still" else point - first
            values.append(
                _to_output_ticks(_time(item["start"]) + offset, _output_base(snapshot))
            )
    return _one_mapping(values)


def _placed_output_to_raw(snapshot, output_ticks, placement_id, track_id):
    from .import_layout import active_placements

    point = output_ticks * _output_base(snapshot)
    values = []
    for item in active_placements(
        snapshot, placement_id=placement_id, track_id=track_id
    ):
        start, end = _time(item["start"]), _time(item["end"])
        if start <= point < end:
            offset = Fraction(0) if item["mediaKind"] == "still" else point - start
            source = _time(item["in"]) + offset
            clock = item["in"]["timebase"]
            ticks = source / Fraction(clock["num"], clock["den"])
            if ticks.denominator != 1:
                raise MappingError(
                    "placed point is not integral in the selected source clock"
                )
            values.append((item["sourceId"], ticks.numerator))
    return _one_mapping(values)


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
