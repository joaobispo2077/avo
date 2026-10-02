"""Conservative local breath proposals from waveform + protected word timings.

No medical inference, model downloads, or automatic promotion of an acoustic
heuristic to a confirmed breath. Review/annotation is required for treatment.
"""

from __future__ import annotations

import numpy as np

from avo.breath_control import BreathControlError


def rms_db(pcm: np.ndarray) -> float:
    return (
        float(
            20
            * np.log10(max(1e-9, float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))))
        )
        if len(pcm)
        else -180.0
    )


def protected_word_ranges(
    words: list[dict], rate: int, *, guard_ms: float = 80, length: int | None = None
) -> list[dict]:
    guard = round(guard_ms * rate / 1000)
    intervals = []
    for word in words:
        interval = _word_range(word, rate, guard, length)
        if interval:
            intervals.append(interval)
    return _merge_ranges(intervals)


def _word_range(word: dict, rate: int, guard: int, length: int | None):
    if word.get("type") == "spacing":
        return None
    start, end = float(word["start"]), float(word["end"])
    if not np.isfinite([start, end]).all() or start < 0 or end < start:
        raise BreathControlError("invalid transcript word range")
    left = max(0, round(start * rate) - guard)
    right = round(end * rate) + guard
    if length is not None:
        right = min(length, right)
    return (left, right) if right > left else None


def _merge_ranges(intervals: list[tuple[int, int]]) -> list[dict]:
    merged = []
    for left, right in sorted(intervals):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return [
        {"startSample": left, "endSampleExclusive": right} for left, right in merged
    ]


def _spectral_features(chunk: np.ndarray, rate: int) -> dict:
    size = min(len(chunk), round(rate * 0.025))
    hop = max(1, round(rate * 0.010))
    frames = np.lib.stride_tricks.sliding_window_view(chunk, size)[::hop]
    power = abs(np.fft.rfft(frames * np.hanning(size), axis=1)) ** 2 + 1e-12
    flatness = np.exp(np.mean(np.log(power), axis=1)) / np.mean(power, axis=1)
    periodicity = np.max(power, axis=1) / np.sum(power, axis=1)
    zcr = np.mean(np.diff(np.signbit(frames), axis=1), axis=1)
    return {
        "flatness": float(np.median(flatness)),
        "tonalRatio": float(np.median(periodicity)),
        "zcr": float(np.median(zcr)),
    }


def _active_regions(chunk: np.ndarray, rate: int) -> list[tuple[int, int]]:
    hop = max(1, round(rate * 0.01))
    padded = np.pad(chunk, (0, (-len(chunk)) % hop))
    levels = np.sqrt(np.mean(padded.reshape(-1, hop).astype(np.float64) ** 2, axis=1))
    floor = max(1e-5, float(np.percentile(levels, 15)))
    peak = float(np.percentile(levels, 90))
    threshold = max(floor * 2, peak * 0.12, 1e-4)
    active = np.flatnonzero(levels > threshold)
    if not len(active):
        return []
    groups = np.split(active, np.flatnonzero(np.diff(active) > 8) + 1)
    return [
        (max(0, int(group[0]) * hop - hop), min(len(chunk), (int(group[-1]) + 2) * hop))
        for group in groups
    ]


def analyze_candidates(
    pcm: np.ndarray,
    sample_rate: int,
    words: list[dict],
    *,
    guard_ms: float = 80,
    protected_ranges: list[dict] | None = None,
) -> dict:
    """Produce an auditable gap inventory; noise-like does not mean breath."""
    if sample_rate <= 0 or pcm.ndim != 1 or not np.isfinite(pcm).all():
        raise BreathControlError("analysis requires finite mono PCM and a sample rate")
    protection = protected_word_ranges(
        words, sample_rate, guard_ms=guard_ms, length=len(pcm)
    )
    all_ranges = protection + (protected_ranges or [])
    gaps = _gaps(all_ranges, len(pcm))
    events, gap_inventory = [], []
    for start, end in gaps:
        gap_inventory.append({"startSample": start, "endSampleExclusive": end})
        events.extend(_gap_events(pcm, sample_rate, start, end))
    for ordinal, event in enumerate(events, 1):
        event["eventId"] = f"breath-candidate-{ordinal:04d}"
    # ponytail: high-precision proposals, not a universal speech/breath classifier.
    # Confirmed annotations can be imported; a validated detector is a future upgrade.
    return {
        "sampleRate": sample_rate,
        "events": events,
        "protectedRanges": all_ranges,
        "gaps": gap_inventory,
        "detector": "local-waveform-proposals-v1",
        "requiresListening": True,
    }


def _gaps(ranges: list[dict], length: int) -> list[tuple[int, int]]:
    boundaries = sorted(
        (item["startSample"], item["endSampleExclusive"]) for item in ranges
    )
    gaps, cursor = [], 0
    for start, end in boundaries:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < length:
        gaps.append((cursor, length))
    return gaps


def _gap_events(pcm: np.ndarray, rate: int, start: int, end: int) -> list[dict]:
    if (end - start) / rate < 0.15:
        return []
    events = []
    for left, right in _active_regions(pcm[start:end], rate):
        left, right = start + left, start + right
        if right - left < rate * 0.15:
            continue
        features = _spectral_features(pcm[left:right], rate)
        noise_like = features["flatness"] >= 0.15 and features["tonalRatio"] <= 0.15
        before = pcm[max(0, start - rate) : start]
        after = pcm[end : min(len(pcm), end + rate)]
        events.append(
            {
                "startSample": left,
                "endSampleExclusive": right,
                "status": "ambiguous",
                "breathRmsDb": round(rms_db(pcm[left:right]), 3),
                "speechRmsDb": round(max(rms_db(before), rms_db(after)), 3),
                "reason": "noise-like; listen to exclude product sounds and untranscribed speech"
                if noise_like
                else "tonal or mixed; manual review required",
            }
        )
    return events
