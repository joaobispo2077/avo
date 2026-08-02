"""Percent-based speech noise reduction for AVO render extracts."""

from __future__ import annotations

from typing import Any

ENGINE_DEFAULT_PCT = 35
MAX_STRENGTH_PCT = 100
SPEECH_NR_CAP_DB = 22.0

PRESET_LABELS: dict[str, int] = {
    "light": 25,
    "standard": 35,
    "medium": 50,
    "strong": 70,
    "aggressive": 85,
}

# Calibration knots: strength_pct -> (nr_db, nf_db)
_AFFTDN_KNOTS: list[tuple[int, float, float]] = [
    (25, 4.0, -40.0),
    (35, 8.0, -35.0),
    (50, 12.0, -32.0),
    (70, 16.0, -30.0),
    (85, 20.0, -28.0),
    (100, 22.0, -27.0),
]

EQ_CHAIN = [
    "highpass=f=90:p=2",
    "equalizer=f=250:t=q:w=1.2:g=-1.5",
    "equalizer=f=3400:t=q:w=1.0:g=1.2",
    "lowpass=f=16000",
]


def clamp_strength_pct(value: int | float) -> int:
    return max(0, min(MAX_STRENGTH_PCT, int(round(value))))


def preset_to_pct(name: str) -> int | None:
    key = name.strip().lower()
    return PRESET_LABELS.get(key)


def label_for_pct(strength_pct: int) -> str:
    pct = clamp_strength_pct(strength_pct)
    if pct == 0:
        return "Off"
    best_name = "Custom"
    best_dist = MAX_STRENGTH_PCT + 1
    for name, preset_pct in PRESET_LABELS.items():
        dist = abs(preset_pct - pct)
        if dist < best_dist:
            best_dist = dist
            best_name = name.capitalize()
    if best_dist <= 3:
        return f"{best_name} {pct}%"
    return f"{pct}%"


def afftdn_params(strength_pct: int) -> tuple[float, float] | None:
    """Return (nr, nf) for afftdn or None when denoise is off."""
    pct = clamp_strength_pct(strength_pct)
    if pct <= 0:
        return None
    if pct <= _AFFTDN_KNOTS[0][0]:
        nr, nf = _AFFTDN_KNOTS[0][1], _AFFTDN_KNOTS[0][2]
        scale = pct / _AFFTDN_KNOTS[0][0]
        return nr * scale, nf
    for (p0, nr0, nf0), (p1, nr1, nf1) in zip(_AFFTDN_KNOTS, _AFFTDN_KNOTS[1:]):
        if pct <= p1:
            if p1 == p0:
                return nr1, nf1
            t = (pct - p0) / (p1 - p0)
            nr = nr0 + t * (nr1 - nr0)
            nf = nf0 + t * (nf1 - nf0)
            return min(nr, SPEECH_NR_CAP_DB), nf
    nr, nf = _AFFTDN_KNOTS[-1][1], _AFFTDN_KNOTS[-1][2]
    return min(nr, SPEECH_NR_CAP_DB), nf


def afftdn_filter(strength_pct: int) -> str:
    params = afftdn_params(strength_pct)
    if params is None:
        return ""
    nr, nf = params
    return f"afftdn=nr={nr:.2f}:nf={nf:.1f}:tn=1"


def build_repair_filter(strength_pct: int) -> str:
    """Full main-speech chain: EQ + optional afftdn + lowpass."""
    parts = [EQ_CHAIN[0], EQ_CHAIN[1], EQ_CHAIN[2]]
    denoise = afftdn_filter(strength_pct)
    if denoise:
        parts.append(denoise)
    parts.append(EQ_CHAIN[3])
    return ",".join(parts)


def restoration_enabled(edl: dict, source_name: str) -> bool:
    audio = edl.get("audio") or {}
    if audio.get("noise_reduction_policy") != "conservative_speech_first":
        return False
    return str(source_name).startswith("main")


def resolve_default_pct(edl: dict, provider: dict | None = None) -> int:
    audio = edl.get("audio") or {}
    if audio.get("restoration_default_pct") is not None:
        return clamp_strength_pct(audio["restoration_default_pct"])
    if provider and provider.get("restoration_default_pct") is not None:
        return clamp_strength_pct(provider["restoration_default_pct"])
    if audio.get("noise_reduction_policy") == "conservative_speech_first":
        return ENGINE_DEFAULT_PCT
    return 0


def _ranges_overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 and b0 < a1


def strength_for_source_range(
    edl: dict,
    source_name: str,
    source_start: float,
    source_end: float,
    provider: dict | None = None,
) -> int:
    if not restoration_enabled(edl, source_name):
        return 0
    strength = resolve_default_pct(edl, provider)
    audio = edl.get("audio") or {}
    for seg in audio.get("restoration_segments") or []:
        seg_start = float(seg["start_in_source"])
        seg_end = float(seg["end_in_source"])
        if _ranges_overlap(source_start, source_end, seg_start, seg_end):
            strength = max(strength, clamp_strength_pct(seg["strength_pct"]))
    return strength


def audio_repair_filter_for(
    edl: dict,
    source_name: str,
    source_start: float | None = None,
    source_end: float | None = None,
    provider: dict | None = None,
) -> str:
    """Return FFmpeg -af chain for a main segment extract."""
    if not restoration_enabled(edl, source_name):
        return ""
    if source_start is not None and source_end is not None:
        pct = strength_for_source_range(edl, source_name, source_start, source_end, provider)
    else:
        pct = resolve_default_pct(edl, provider)
    if pct <= 0:
        return ""
    return build_repair_filter(pct)


def validate_restoration_segments(audio: dict) -> list[str]:
    errors: list[str] = []
    default_pct = audio.get("restoration_default_pct")
    if default_pct is not None:
        try:
            pct = int(default_pct)
        except (TypeError, ValueError):
            errors.append("audio.restoration_default_pct must be an integer 0-100")
        else:
            if pct < 0 or pct > MAX_STRENGTH_PCT:
                errors.append("audio.restoration_default_pct must be between 0 and 100")

    segments = audio.get("restoration_segments")
    if segments is None:
        return errors
    if not isinstance(segments, list):
        errors.append("audio.restoration_segments must be an array")
        return errors

    parsed: list[tuple[float, float, int]] = []
    for index, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errors.append(f"audio.restoration_segments[{index}] must be an object")
            continue
        for field in ("start_in_source", "end_in_source", "strength_pct"):
            if field not in seg:
                errors.append(f"audio.restoration_segments[{index}] missing {field}")
        try:
            start = float(seg["start_in_source"])
            end = float(seg["end_in_source"])
            pct = clamp_strength_pct(seg["strength_pct"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            errors.append(f"audio.restoration_segments[{index}] end must be after start")
        if pct < 0 or pct > MAX_STRENGTH_PCT:
            errors.append(f"audio.restoration_segments[{index}].strength_pct out of range")
        if pct > 50 and not seg.get("approved_by_user"):
            errors.append(
                f"audio.restoration_segments[{index}] above 50% requires approved_by_user"
            )
        parsed.append((start, end, index))

    for i, (s0, e0, idx0) in enumerate(parsed):
        for s1, e1, idx1 in parsed[i + 1 :]:
            if _ranges_overlap(s0, e0, s1, e1):
                errors.append(
                    f"audio.restoration_segments[{idx0}] overlaps [{idx1}]"
                )
    return errors
