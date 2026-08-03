"""Percent-based regional dialogue gain for AVO render extracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from avo import audio_analysis
from avo import audio_restoration

ENGINE_DEFAULT_BOOST_PCT = 0
MAX_BOOST_PCT = 100
MAX_BOOST_DB = 6.0
APPROVAL_THRESHOLD_PCT = 40

PRESET_LABELS: dict[str, int] = {
    "light": 15,
    "standard": 25,
    "medium": 40,
    "strong": 60,
}

# boost_pct -> dB (cap +6 dB unless approved segment exceeds via explicit pct)
_BOOST_KNOTS: list[tuple[int, float]] = [
    (15, 1.5),
    (25, 2.5),
    (40, 4.0),
    (60, 6.0),
    (100, 6.0),
]

QUIET_SUGGEST_THRESHOLD = 0.55


@dataclass
class GainSuggestion:
    start: float
    end: float
    quiet_score: float
    suggested_boost_pct: int
    confidence: str
    reason: str = "quiet_dialogue"

    def to_dict(self) -> dict:
        return asdict(self)


def clamp_boost_pct(value: int | float) -> int:
    return max(0, min(MAX_BOOST_PCT, int(round(value))))


def boost_db_from_pct(boost_pct: int, *, approved: bool = False) -> float:
    pct = clamp_boost_pct(boost_pct)
    if pct <= 0:
        return 0.0
    if pct <= _BOOST_KNOTS[0][0]:
        db = _BOOST_KNOTS[0][1] * (pct / _BOOST_KNOTS[0][0])
    else:
        db = _BOOST_KNOTS[-1][1]
        for (p0, d0), (p1, d1) in zip(_BOOST_KNOTS, _BOOST_KNOTS[1:]):
            if pct <= p1:
                if p1 == p0:
                    db = d1
                else:
                    t = (pct - p0) / (p1 - p0)
                    db = d0 + t * (d1 - d0)
                break
    cap = MAX_BOOST_DB if approved or pct <= APPROVAL_THRESHOLD_PCT else MAX_BOOST_DB
    return min(db, cap)


def volume_filter(boost_pct: int, *, approved: bool = False) -> str:
    db = boost_db_from_pct(boost_pct, approved=approved)
    if db <= 0.01:
        return ""
    return f"volume={db:.2f}dB"


def suggested_boost_pct_from_score(score: float) -> int:
    if score < QUIET_SUGGEST_THRESHOLD:
        return 0
    if score < 0.65:
        return 15
    if score < 0.75:
        return 25
    if score < 0.85:
        return 40
    return 60


def _quiet_score(word_rms: float, reference_rms: float) -> float:
    if reference_rms <= 1e-9:
        reference_rms = 1e-9
    ratio = word_rms / reference_rms
    return min(1.0, max(0.0, (0.85 - ratio) / 0.55))


def _merge_gain_segments(
    segments: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    if not segments:
        return []
    segments = sorted(segments, key=lambda s: s[0])
    merged: list[tuple[float, float, float]] = [segments[0]]
    for start, end, score in segments[1:]:
        ps, pe, pscore = merged[-1]
        if start <= pe + 0.15:
            merged[-1] = (ps, max(pe, end), max(pscore, score))
        else:
            merged.append((start, end, score))
    return merged


def suggest_gain_from_transcript(
    media: Path,
    transcript: Path,
    duration: float,
) -> list[GainSuggestion]:
    from avo.timeline_view import words_in_range

    words = words_in_range(transcript, 0.0, duration)
    if not words:
        return []

    pcm = audio_analysis.extract_pcm_mono(media, 0.0, duration)
    sr = audio_analysis.ANALYSIS_SAMPLE_RATE
    word_rms_values: list[tuple[float, float, float]] = []
    speech_rms_samples: list[float] = []

    for w in words:
        if w.get("type") == "spacing":
            continue
        ws = max(0, int(float(w["start"]) * sr))
        we = min(len(pcm), int(float(w["end"]) * sr))
        if we <= ws:
            continue
        chunk = pcm[ws:we]
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        speech_rms_samples.append(rms)
        word_rms_values.append((float(w["start"]), float(w["end"]), rms))

    if not speech_rms_samples:
        return []

    reference = float(np.median(speech_rms_samples))
    raw_segments: list[tuple[float, float, float]] = []
    for start, end, rms in word_rms_values:
        score = _quiet_score(rms, reference)
        if score >= QUIET_SUGGEST_THRESHOLD:
            raw_segments.append((start, end, score))

    suggestions: list[GainSuggestion] = []
    for start, end, score in _merge_gain_segments(raw_segments):
        if end - start < 0.15:
            continue
        suggestions.append(
            GainSuggestion(
                start=round(start, 3),
                end=round(end, 3),
                quiet_score=round(score, 3),
                suggested_boost_pct=suggested_boost_pct_from_score(score),
                confidence="high",
            )
        )
    suggestions.sort(key=lambda s: s.quiet_score, reverse=True)
    return suggestions


def suggest_gain(
    media: Path,
    transcript: Path | None = None,
) -> list[GainSuggestion]:
    duration = audio_analysis.media_duration(media)
    if transcript and transcript.exists():
        return suggest_gain_from_transcript(media, transcript, duration)
    return []


def gain_enabled(edl: dict, source_name: str) -> bool:
    audio = edl.get("audio") or {}
    if audio.get("gain_policy") != "level_match_speech":
        if not audio.get("gain_segments") and not audio.get("gain_default_pct"):
            return False
    return str(source_name).startswith("main")


def resolve_default_boost_pct(edl: dict, provider: dict | None = None) -> int:
    audio = edl.get("audio") or {}
    if audio.get("gain_default_pct") is not None:
        return clamp_boost_pct(audio["gain_default_pct"])
    if provider and provider.get("gain_default_pct") is not None:
        return clamp_boost_pct(provider["gain_default_pct"])
    if audio.get("gain_policy") == "level_match_speech":
        return PRESET_LABELS["standard"]
    return ENGINE_DEFAULT_BOOST_PCT


def boost_for_source_range(
    edl: dict,
    source_name: str,
    source_start: float,
    source_end: float,
    provider: dict | None = None,
) -> tuple[int, bool]:
    if not gain_enabled(edl, source_name):
        return 0, False
    boost = resolve_default_boost_pct(edl, provider)
    segment_approved = False
    audio = edl.get("audio") or {}
    for seg in audio.get("gain_segments") or []:
        seg_start = float(seg["start_in_source"])
        seg_end = float(seg["end_in_source"])
        if audio_restoration._ranges_overlap(source_start, source_end, seg_start, seg_end):
            pct = clamp_boost_pct(seg["boost_pct"])
            if pct >= boost:
                boost = pct
                segment_approved = bool(seg.get("approved_by_user"))
            elif seg.get("approved_by_user"):
                segment_approved = True
    if boost <= APPROVAL_THRESHOLD_PCT:
        return boost, True
    return boost, segment_approved


def gain_filter_for(
    edl: dict,
    source_name: str,
    source_start: float | None = None,
    source_end: float | None = None,
    provider: dict | None = None,
) -> str:
    if not gain_enabled(edl, source_name):
        return ""
    if source_start is not None and source_end is not None:
        pct, approved = boost_for_source_range(edl, source_name, source_start, source_end, provider)
    else:
        pct = resolve_default_boost_pct(edl, provider)
        approved = pct <= APPROVAL_THRESHOLD_PCT
    if pct <= 0:
        return ""
    if pct > APPROVAL_THRESHOLD_PCT and not approved:
        return ""
    return volume_filter(pct, approved=approved)


def validate_gain_segments(audio: dict) -> list[str]:
    errors: list[str] = []
    default_pct = audio.get("gain_default_pct")
    if default_pct is not None:
        try:
            pct = int(default_pct)
        except (TypeError, ValueError):
            errors.append("audio.gain_default_pct must be an integer 0-100")
        else:
            if pct < 0 or pct > MAX_BOOST_PCT:
                errors.append("audio.gain_default_pct must be between 0 and 100")

    segments = audio.get("gain_segments")
    if segments is None:
        return errors
    if not isinstance(segments, list):
        errors.append("audio.gain_segments must be an array")
        return errors

    parsed: list[tuple[float, float, int]] = []
    for index, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errors.append(f"audio.gain_segments[{index}] must be an object")
            continue
        for field in ("start_in_source", "end_in_source", "boost_pct"):
            if field not in seg:
                errors.append(f"audio.gain_segments[{index}] missing {field}")
        try:
            start = float(seg["start_in_source"])
            end = float(seg["end_in_source"])
            pct = clamp_boost_pct(seg["boost_pct"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            errors.append(f"audio.gain_segments[{index}] end must be after start")
        if pct > APPROVAL_THRESHOLD_PCT and not seg.get("approved_by_user"):
            errors.append(
                f"audio.gain_segments[{index}] above {APPROVAL_THRESHOLD_PCT}% requires approved_by_user"
            )
        parsed.append((start, end, index))

    for i, (s0, e0, idx0) in enumerate(parsed):
        for s1, e1, idx1 in parsed[i + 1 :]:
            if audio_restoration._ranges_overlap(s0, e0, s1, e1):
                errors.append(f"audio.gain_segments[{idx0}] overlaps [{idx1}]")
    return errors


def preview_gain_segment(
    media: Path,
    start: float,
    end: float,
    boost_pct: int,
    out_dir: Path,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = end - start
    before = out_dir / f"gain_preview_{start:.1f}-{end:.1f}_before.wav"
    after = out_dir / f"gain_preview_{start:.1f}-{end:.1f}_after_{boost_pct}pct.wav"
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(media),
            "-t",
            f"{duration:.3f}",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "48000",
            str(before),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    filt = volume_filter(boost_pct, approved=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(before), "-af", filt, str(after)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"before": str(before), "after": str(after)}
