"""Qualify an explicitly selected word from current source-bound metadata only."""

from copy import deepcopy
from fractions import Fraction

from .contracts import content_hash, validate_document
from .cutting_contracts import source_interval
from .event_clock import sample_rate_boundary
from .motion_metadata import METADATA_LIMITS, _check_budget
from .preparation import _interval, inspect_speech_coverage


def _current_models(bound, current):
    _check_budget({"bound": bound, "current": current}, METADATA_LIMITS)
    if not isinstance(bound, dict) or bound != current:
        raise ValueError(
            "Word evidence model/runtime bindings changed or are unavailable"
        )
    for role in ("transcription", "alignment"):
        record = bound.get(role) or {}
        if not isinstance(record, dict):
            raise ValueError("Word model dependency evidence is malformed")
        files = record.get("files")
        if (
            record.get("status") != "observed"
            or not isinstance(files, dict)
            or not files
        ):
            raise ValueError("Word anchors require prepared ASR and alignment evidence")
        for digest in files.values():
            validate_document(digest, "avo.cutting.schema.json#/$defs/sha256")


def _selected_word(analysis, index, expected):
    words = analysis.get("words") or []
    if type(index) is not int or not 0 <= index < len(words):
        raise ValueError("Selected word index is unavailable")
    word = words[index]
    if not isinstance(word, dict) or content_hash(word) != expected:
        raise ValueError("Selected word text or timing changed")
    if (
        word.get("alignmentStatus") != "aligned"
        or word.get("eligibleEdge") is not True
        or not str(word.get("text") or "").strip()
    ):
        raise ValueError("Selected word has no qualified aligned timing")
    return word


def _unprotected_word(span, ranges, source_range):
    identity, first, end = source_interval(source_range)
    for value in ranges:
        source, start, finish = source_interval(value)
        if source != identity or not first <= start < finish <= end:
            raise ValueError("Word protection escapes its original source unit")
        if max(start, span[0]) < min(finish, span[1]):
            raise ValueError("Selected word overlaps unresolved or unmeasured evidence")


def _native_start(word, source_range, frame_rate):
    if not isinstance(frame_rate, Fraction) or frame_rate <= 0:
        raise ValueError("Word anchors require a positive rational program clock")
    base = source_range["timebase"]
    scale = Fraction(base["num"], base["den"])
    if scale * frame_rate > 1:
        raise ValueError("Source clock is too coarse for a word-exact program anchor")
    point = Fraction(str(word["start"])) / scale
    ticks = sample_rate_boundary(
        point.numerator, source_rate=point.denominator, target_rate=1
    )
    if not source_range["startTicks"] <= ticks < source_range["endTicksExclusive"]:
        raise ValueError("Rounded word start is outside its original source unit")
    return {"ticks": ticks, "timebase": deepcopy(base)}


def word_source_time(
    analysis,
    *,
    source_ref,
    source_range,
    routing,
    sync_ref,
    model_bindings,
    current_bindings,
    word_index,
    word_hash,
    frame_rate,
    protected_ranges=None,
):
    """Return a qualified word start; never infer timing, select text or approve."""
    _current_models(model_bindings, current_bindings)
    coverage = inspect_speech_coverage(
        analysis,
        source_ref=source_ref,
        source_range=source_range,
        routing=routing,
        sync_ref=sync_ref,
    )
    if coverage["status"] in {"stale", "unavailable"}:
        raise ValueError("Current measured source/Sync/routing evidence is unavailable")
    alignment = analysis.get("alignment")
    if not isinstance(alignment, dict) or alignment.get("status") != "pass":
        raise ValueError("Word alignment evidence is unavailable")
    word = _selected_word(analysis, word_index, word_hash)
    span = _interval(word, source_interval(source_range)[1:])
    protected_ranges = [] if protected_ranges is None else protected_ranges
    _check_budget(protected_ranges, METADATA_LIMITS)
    _unprotected_word(
        span, (*coverage["protectedRanges"], *protected_ranges), source_range
    )
    return _native_start(word, source_range, frame_rate)
