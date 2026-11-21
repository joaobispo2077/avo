"""Relate explicitly selected prepared words to an observed reference clock."""

from fractions import Fraction
from math import ceil

from avo.reference_timing import _audio_relationships

from .contracts import content_hash
from .sound_word_evidence import WordEvidenceReader

WORD_ERRORS = (ValueError, RuntimeError, OSError, KeyError, TypeError)


def _seconds_per_tick(clock):
    return Fraction(clock["num"], clock["den"])


def _word_timing(reader, anchor, clip, observation, audio):
    scope = clip["sourceRange"]
    video_tick = _seconds_per_tick(scope["timebase"])
    sample_rate = audio["sampleRate"]
    preview_rate = 1 / (video_tick * observation["coverage"]["minimumGapTicks"])
    frozen = reader.anchor(
        anchor, frame_rate=preview_rate, expected_audio=clip["audio"]
    )
    point = frozen["sourceTime"]
    word_tick = _seconds_per_tick(point["timebase"])
    position = audio["streamOriginSample"] + point["ticks"] * word_tick * sample_rate
    if not audio["startSample"] <= position < audio["endSampleExclusive"]:
        raise ValueError("Prepared word is outside observed reference audio")
    sample = round(position)
    radius = audio["clockUncertaintySamples"] + max(1, ceil(word_tick * sample_rate))
    interpretation = observation["interpretation"]
    word_clock = {
        "sampleRate": sample_rate,
        "windowSamples": 0,
        "clockUncertaintySamples": radius,
        "onsetSamples": [sample],
    }
    matches = _audio_relationships(
        interpretation.get("timingCandidates", []), scope, word_clock
    )
    return {
        "status": "observed",
        "anchor": frozen,
        "startSample": sample,
        "clockUncertaintySamples": radius,
        "revealWindows": [
            {"startTicks": row["startTicks"], "endTicks": row["endTicks"]}
            for row in matches
        ],
    }


def _measure_words(workspace, clip, observation, audio):
    unavailable = {"status": "unavailable", "reason": "unverified-word-evidence"}
    selections = clip["wordAnchors"]
    if audio.get("streamOriginSample") is None:
        return [unavailable] * len(selections)
    try:
        reader = WordEvidenceReader(workspace)
    except WORD_ERRORS:
        return [unavailable] * len(selections)
    rows = []
    for anchor in selections:
        try:
            rows.append(_word_timing(reader, anchor, clip, observation, audio))
        except WORD_ERRORS:
            rows.append(unavailable)
    try:
        reader.recheck()
    except WORD_ERRORS:
        return [unavailable] * len(selections)
    return rows


def add_reference_words(workspace, clip, observation):
    if "wordAnchors" not in clip:
        return
    details = observation["interpretation"]
    rows = _measure_words(workspace, clip, observation, details["audioTiming"])
    details["wordTiming"] = rows
    details["availableEvidence"]["prepared-words"] = (
        "observed"
        if any(row["status"] == "observed" for row in rows)
        else "unavailable"
    )
    observation["analysisHash"] = content_hash(
        {key: value for key, value in observation.items() if key != "analysisHash"}
    )
