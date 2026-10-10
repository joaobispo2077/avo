"""Conservative source-clock pause proposals, never a timeline authority."""

from __future__ import annotations

from fractions import Fraction
from math import ceil, floor

from .cutting_contracts import validate_source_range
from .cutting_policy import CuttingPolicy, pause_retention


def _seconds(interval):
    validate_source_range(interval)
    basis = interval["timebase"]
    scale = Fraction(basis["num"], basis["den"])
    return interval["startTicks"] * scale, interval["endTicksExclusive"] * scale


def _overlaps(left, right):
    if left["sourceId"] != right["sourceId"]:
        return False
    a, b = _seconds(left)
    c, d = _seconds(right)
    return a < d and c < b


def _quiet_covers(interval, quiet_ranges):
    first, last = _seconds(interval)
    ranges = sorted(
        _seconds(item)
        for item in quiet_ranges
        if item["sourceId"] == interval["sourceId"]
    )
    cursor = first
    for start, end in ranges:
        if start > cursor:
            break
        cursor = max(cursor, end)
        if cursor >= last:
            return True
    return False


def _word_clock_uncertainties(gap, evidence):
    reasons = []
    edges = evidence.get("wordEdges") or {}
    if edges.get("status") != "observed":
        reasons.append("word edges are missing or estimated")
    before, after = edges.get("beforeEndTicks"), edges.get("afterStartTicks")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (before, after)):
        reasons.append("word edge clock is unavailable")
    elif before > gap["startTicks"] or after < gap["endTicksExclusive"]:
        reasons.append("retained speech conflicts with the proposed gap")
    return reasons


def _word_uncertainties(gap, evidence):
    reasons = _word_clock_uncertainties(gap, evidence)
    adjacent = evidence.get("adjacentWords") or {}
    if not adjacent.get("before") or not adjacent.get("after"):
        reasons.append("adjacent retained words are unavailable")
    return reasons


def _acoustic_uncertainties(gap, evidence):
    reasons = []
    if evidence.get("acousticObserved") is not True:
        reasons.append("acoustic coverage is missing")
    if any(_overlaps(gap, item) for item in evidence.get("speechRanges", [])):
        reasons.append("the gap contains observed speech omitted by ASR")
    if not _quiet_covers(gap, evidence.get("quietRanges", [])):
        reasons.append("quiet acoustic space is not completely observed")
    return reasons


def _uncertainties(gap, evidence):
    reasons = _word_uncertainties(gap, evidence) + _acoustic_uncertainties(
        gap, evidence
    )
    context = evidence.get("context") or {}
    if (
        context.get("dispensable") is not True
        or context.get("intentionalPause") is not False
    ):
        reasons.append("the pause's editorial function is uncertain")
    return reasons


def _removed_range(gap, policy, retained_ms, frame_rate):
    scale = Fraction(gap["timebase"]["num"], gap["timebase"]["den"])
    outgoing_ms = policy.effective["guards"]["afterMs"]
    incoming_ms = retained_ms - outgoing_ms
    start = gap["startTicks"] + ceil(Fraction(outgoing_ms, 1000) / scale)
    end = gap["endTicksExclusive"] - ceil(Fraction(incoming_ms, 1000) / scale)
    if frame_rate:
        fps = Fraction(frame_rate["num"], frame_rate["den"])
        if fps <= 0:
            raise ValueError("frame rate must be positive")
        start = ceil(Fraction(ceil(start * scale * fps), 1) / fps / scale)
        end = floor(Fraction(floor(end * scale * fps), 1) / fps / scale)
    return {**gap, "startTicks": start, "endTicksExclusive": end}


def propose_pause(
    gap: dict,
    policy: CuttingPolicy,
    evidence: dict,
    *,
    frame_rate: dict | None = None,
) -> dict:
    """Require aligned words, acoustic quiet space, context and hard protection."""
    validate_source_range(gap)
    first, last = _seconds(gap)
    duration_ms = floor((last - first) * 1000)
    result = {
        "disposition": "keep",
        "sourceRange": gap,
        "categories": ["excess-silence"],
        "reasons": [],
    }
    protected = any(_overlaps(gap, item["sourceRange"]) for item in policy.protections)
    preference = pause_retention(
        duration_ms, policy, confirmed_dispensable=True, protected=protected
    )
    result["retainedMs"] = preference["retainedMs"]
    if not policy.enabled or protected or preference["action"] == "keep":
        result["reasons"] = ["protected or retained by effective pacing policy"]
        return result
    uncertainty = _uncertainties(gap, evidence)
    if uncertainty:
        return {**result, "disposition": "needs-review", "reasons": uncertainty}
    removed = _removed_range(gap, policy, preference["retainedMs"], frame_rate)
    if removed["endTicksExclusive"] <= removed["startTicks"]:
        return {**result, "reasons": ["no removable space remains after quantization"]}
    start, end = _seconds(removed)
    return {
        **result,
        "disposition": "shorten",
        "removeRange": removed,
        "retainedMs": float((last - first - (end - start)) * 1000),
        "adjacentWords": evidence["adjacentWords"],
        "reasons": [
            "aligned complete speech and independently observed dispensable quiet space"
        ],
    }
