"""Source-bound preparation evidence. Inspection never decodes or runs a model."""

from copy import deepcopy
from fractions import Fraction
from math import ceil, floor, isfinite

from .contracts import content_hash, validate_document
from .cutting_contracts import source_interval, validate_source_range
from .motion_metadata import METADATA_LIMITS, _check_budget

SCHEMA = "avo.preparation.schema.json"


def _analysis_facts(analysis):
    if not isinstance(analysis, dict):
        raise ValueError("Source analysis must be a metadata object")
    keys = (
        "sourceRef",
        "routing",
        "syncRef",
        "preprocessing",
        "status",
        "coverage",
        "vad",
        "words",
        "tools",
    )
    facts = {key: analysis.get(key) for key in keys}
    alignment = analysis.get("alignment")
    facts["alignmentStatus"] = (
        alignment.get("status") if isinstance(alignment, dict) else None
    )
    _check_budget(facts, METADATA_LIMITS)
    return facts


def _coverage_binding(facts, source_ref, source_range, routing, sync_ref):
    if not isinstance(routing, dict):
        raise ValueError("Source routing must be an explicit metadata object")
    validate_document(source_ref, "avo.cutting.schema.json#/$defs/artifactRef")
    validate_document(sync_ref, "avo.cutting.schema.json#/$defs/artifactRef")
    validate_source_range(source_range)
    _check_budget(routing, METADATA_LIMITS)
    return {
        "sourceRef": deepcopy(source_ref),
        "sourceRange": deepcopy(source_range),
        "routing": {
            "streamIndex": routing.get("streamIndex"),
            "channels": deepcopy(routing.get("channels", [])),
        },
        "routingHash": content_hash(routing),
        "syncRef": deepcopy(sync_ref),
        "analysisFactsHash": content_hash(facts),
        "transcriptHash": content_hash(
            {"words": facts["words"], "alignmentStatus": facts["alignmentStatus"]}
        ),
        "modelOptionsHash": content_hash(
            {"tools": facts["tools"], "preprocessing": facts["preprocessing"]}
        ),
    }


def _binding_issues(facts, binding, routing):
    expected = {
        "sourceRef": binding["sourceRef"],
        "routing": routing,
        "syncRef": binding["syncRef"],
    }
    issues = [
        key + ("-changed" if facts[key] else "-unavailable")
        for key, value in expected.items()
        if facts[key] != value
    ]
    preprocessing = facts["preprocessing"]
    observed_range = (
        preprocessing.get("sourceRange") if isinstance(preprocessing, dict) else None
    )
    if observed_range != binding["sourceRange"]:
        issues.append(
            "source-range-changed" if observed_range else "source-range-unavailable"
        )
    return issues


def _seconds(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise ValueError("Observation timing requires finite seconds")
    return Fraction(str(value))


def _interval(value, bounds):
    first, end = _seconds(value["start"]), _seconds(value["end"])
    if not bounds[0] <= first < end <= bounds[1]:
        raise ValueError("Observation interval is outside its measured source coverage")
    return first, end


def _union(intervals):
    result = []
    for first, end in sorted(intervals):
        if result and first <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((first, end))
    return result


def _uncovered(activity, words):
    words = iter(words)
    word = next(words, None)
    for first, end in activity:
        cursor = first
        while word is not None and word[1] <= first:
            word = next(words, None)
        while word is not None and word[0] < end:
            if word[0] > cursor:
                yield cursor, word[0]
            cursor = max(cursor, min(word[1], end))
            if word[1] >= end:
                break
            word = next(words, None)
        if cursor < end:
            yield cursor, end


def _reliable_words(facts, bounds, issues, measured):
    if facts["alignmentStatus"] != "pass":
        issues.append("word-alignment-unavailable")
        return []
    result = []
    for word in facts["words"] or []:
        if (
            not isinstance(word, dict)
            or word.get("alignmentStatus") != "aligned"
            or not str(word.get("text") or "").strip()
        ):
            issues.append("word-timing-unreliable")
            continue
        try:
            result.append(_measured_interval(word, bounds, measured))
        except (ValueError, TypeError, KeyError):
            issues.append("word-timing-unreliable")
    return _union(result)


def _measured_windows(coverage, bounds):
    if "intervals" not in coverage:
        return [_interval(coverage, bounds)]
    windows = coverage["intervals"]
    if (
        "start" in coverage
        or "end" in coverage
        or not isinstance(windows, list)
        or not 1 <= len(windows) <= 128
    ):
        raise ValueError("Measured coverage requires bounded, unambiguous windows")
    return _union(_interval(row, bounds) for row in windows)


def _measured_interval(row, bounds, measured):
    interval = _interval(row, bounds)
    if not any(first <= interval[0] < interval[1] <= end for first, end in measured):
        raise ValueError("Observation crosses an unmeasured source interval")
    return interval


def _source_range(interval, requested):
    scale = Fraction(requested["timebase"]["num"], requested["timebase"]["den"])
    return {
        "sourceId": requested["sourceId"],
        "startTicks": max(requested["startTicks"], floor(interval[0] / scale)),
        "endTicksExclusive": min(
            requested["endTicksExclusive"], ceil(interval[1] / scale)
        ),
        "timebase": deepcopy(requested["timebase"]),
    }


def _observation(kind, interval, binding):
    value = {
        "kind": kind,
        "sourceRange": _source_range(interval, binding["sourceRange"]),
    }
    return {
        "observationId": "speech-gap-"
        + content_hash({"binding": binding, **value})[:24],
        **value,
        "speechConfirmed": False,
        "disposition": "unresolved",
    }


def _coverage_result(binding, status, observations, issues):
    requested = binding["sourceRange"]
    if status in {"unavailable", "stale"}:
        protected = [deepcopy(requested)]
    else:
        intervals = [source_interval(row["sourceRange"])[1:] for row in observations]
        protected = [
            _source_range(interval, requested) for interval in _union(intervals)
        ]
    result = {
        "contractVersion": "1.0.0",
        "binding": binding,
        "status": status,
        "observations": observations,
        "protectedRanges": protected,
        "issues": list(dict.fromkeys(issues)),
        "authorization": "none",
        "automaticRecovery": False,
        "assessment": "available-evidence-only",
        "protectionRounding": "outward-to-source-ticks",
    }
    result["coverageHash"] = content_hash(result)
    validate_document(result, SCHEMA + "#/$defs/coverage")
    return result


def _has_coverage_facts(facts, binding):
    return (
        facts["status"] == "pass"
        and isinstance(facts["vad"], list)
        and isinstance(facts["words"], list)
        and isinstance(facts["tools"], list)
        and bool(facts["tools"])
        and binding["routing"]["streamIndex"] is not None
        and bool(binding["routing"]["channels"])
    )


def _observations(facts, binding, issues):
    requested = source_interval(binding["sourceRange"])[1:]
    coverage = facts["coverage"] or {}
    if (
        not isinstance(coverage, dict)
        or coverage.get("observed") is not True
        or not _has_coverage_facts(facts, binding)
    ):
        raise ValueError("Source acoustics or model/runtime provenance is unavailable")
    measured = _measured_windows(coverage, requested)
    activity = _union(
        _measured_interval(row, requested, measured) for row in facts["vad"] or []
    )
    words = _reliable_words(facts, requested, issues, measured)
    result = [
        _observation("possible-speech-without-reliable-words", interval, binding)
        for interval in _uncovered(activity, words)
    ]
    result.extend(
        _observation("unmeasured", interval, binding)
        for interval in _uncovered([requested], measured)
    )
    return result


def inspect_speech_coverage(analysis, *, source_ref, source_range, routing, sync_ref):
    """Inspect supplied facts only; acoustic gaps never establish confirmed speech.

    Missing/stale inputs protect the complete requested source interval. Measured
    candidates protect outward-rounded original ticks until their normal review.
    No CMap, transcript, recovery attempt or approval is created by inspection.
    """
    facts = _analysis_facts(analysis)
    binding = _coverage_binding(facts, source_ref, source_range, routing, sync_ref)
    validate_document(binding, SCHEMA + "#/$defs/coverageBinding")
    issues = _binding_issues(facts, binding, routing)
    if issues:
        status = (
            "stale"
            if any(issue.endswith("-changed") for issue in issues)
            else "unavailable"
        )
        return _coverage_result(binding, status, [], issues)
    try:
        observations = _observations(facts, binding, issues)
    except (ValueError, KeyError, TypeError) as error:
        return _coverage_result(binding, "unavailable", [], [str(error)[:300]])
    status = "needs-review" if observations else "no-observed-gaps"
    return _coverage_result(binding, status, observations, issues)


def coverage_protections(coverage):
    """Expose current uncertainty through existing cutting protection contracts."""
    validate_document(coverage, SCHEMA + "#/$defs/coverage")
    if coverage["coverageHash"] != content_hash(
        {key: value for key, value in coverage.items() if key != "coverageHash"}
    ):
        raise ValueError("Speech coverage identity changed")
    source = coverage["binding"]["sourceRef"]
    return tuple(
        {
            "eventId": "speech-coverage-"
            + content_hash({"source": source, "range": interval})[:24],
            "role": "uncertain-speech",
            "reason": "Speech completeness remains unmeasured or unresolved",
            "sourceRange": deepcopy(interval),
            "sourceFingerprint": deepcopy(source),
        }
        for interval in coverage["protectedRanges"]
    )
