"""Contextual cutting preview grouping on explicit program-frame clocks."""

from copy import deepcopy
from fractions import Fraction

from .cutting_contracts import selected_source_range, source_interval


def _terminal_trim(outer, retained, edits, *, beginning):
    identity = outer["segmentId"]
    if retained["segmentId"].rpartition("-cut-")[0] != identity:
        return []
    raw, original_first, original_last = source_interval(selected_source_range(outer))
    retained_raw, kept_first, kept_last = source_interval(
        selected_source_range(retained)
    )
    if raw != retained_raw:
        return []
    first, last = (
        (original_first, kept_first) if beginning else (kept_last, original_last)
    )
    return [
        (beginning, edit["occurrenceId"])
        for edit in edits
        if edit["segmentId"] == identity
        and source_interval(edit["removeRange"]) == (raw, first, last)
    ]


def editor_terminal_trims(original, candidate, edits):
    """Find exact retained boundaries for editor changes that create no join."""
    before, after = original["segments"], candidate["segments"]
    if not before or not after:
        return []
    return _terminal_trim(before[0], after[0], edits, beginning=True) + _terminal_trim(
        before[-1], after[-1], edits, beginning=False
    )


def _validate_window(first, last):
    if (
        any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (first, last)
        )
        or not 0 <= first < last
    ):
        raise ValueError("preview windows require nonempty half-open integer frames")


def group_preview_windows(windows, frame_rate, *, maximum_seconds=180):
    """Group whole case windows; a complete long case remains indivisible."""
    fps = Fraction(frame_rate["num"], frame_rate["den"])
    if fps <= 0 or maximum_seconds <= 0:
        raise ValueError("preview frame rate and duration target must be positive")
    maximum = maximum_seconds * fps
    grouped = []
    for item in sorted(windows, key=lambda value: value["startFrame"]):
        window = deepcopy(item)
        first, last = window["startFrame"], window["endFrameExclusive"]
        _validate_window(first, last)
        window["occurrenceIds"] = sorted(set(window.get("occurrenceIds", [])))
        previous = grouped[-1] if grouped else None
        if previous and last - previous["startFrame"] <= maximum:
            previous["endFrameExclusive"] = max(previous["endFrameExclusive"], last)
            previous["occurrenceIds"] = sorted(
                set(previous["occurrenceIds"]) | set(window["occurrenceIds"])
            )
        else:
            grouped.append(window)
    return grouped
