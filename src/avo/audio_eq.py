"""Read-only EQ heuristics and suggestion helpers for AVO /avo.sound."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from avo import audio_analysis

ANALYSIS_SAMPLE_RATE = audio_analysis.ANALYSIS_SAMPLE_RATE
EQ_SUGGEST_THRESHOLD = 0.55
WINDOW_SEC = audio_analysis.WINDOW_SEC
WINDOW_STEP_SEC = audio_analysis.WINDOW_STEP_SEC

ISSUE_RECOMMENDATIONS: dict[str, str] = {
    "mud": "Consider subtractive EQ around 250 Hz (mud/boxiness)",
    "harsh": "Consider taming 5–8 kHz (harsh sibilance or presence)",
    "thin": "Consider conservative presence boost around 3 kHz",
    "rumble": "Consider high-pass near 90–100 Hz (rumble/low-end buildup)",
}


@dataclass
class EqSuggestion:
    start: float
    end: float
    issue_type: str
    severity: str
    score: float
    confidence: str
    recommendation: str

    def to_dict(self) -> dict:
        return asdict(self)


def _band_energy(pcm: np.ndarray, sample_rate: int, low_hz: float, high_hz: float) -> float:
    if len(pcm) < 8:
        return 0.0
    spectrum = np.abs(np.fft.rfft(pcm))
    freqs = np.fft.rfftfreq(len(pcm), 1.0 / sample_rate)
    mask = (freqs >= low_hz) & (freqs < high_hz)
    if not np.any(mask):
        return 0.0
    return float(np.mean(spectrum[mask] ** 2))


def band_ratios(pcm: np.ndarray, sample_rate: int = ANALYSIS_SAMPLE_RATE) -> dict[str, float]:
    rumble = _band_energy(pcm, sample_rate, 20.0, 100.0)
    mud = _band_energy(pcm, sample_rate, 150.0, 400.0)
    speech = _band_energy(pcm, sample_rate, 1000.0, 4000.0)
    presence = _band_energy(pcm, sample_rate, 2000.0, 4500.0)
    harsh = _band_energy(pcm, sample_rate, 5000.0, 8000.0)
    ref = max(speech, 1e-12)
    return {
        "rumble": rumble / ref,
        "mud": mud / ref,
        "speech": 1.0,
        "thin": presence / ref,
        "harsh": harsh / ref,
    }


def _severity(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"


def _score_issue(ratios: dict[str, float], issue_type: str) -> float:
    if issue_type == "mud":
        return min(1.0, max(0.0, (ratios["mud"] - 0.9) / 1.1))
    if issue_type == "harsh":
        return min(1.0, max(0.0, (ratios["harsh"] - 0.75) / 1.0))
    if issue_type == "thin":
        return min(1.0, max(0.0, (0.85 - ratios["thin"]) / 0.55))
    if issue_type == "rumble":
        return min(1.0, max(0.0, (ratios["rumble"] - 0.8) / 1.0))
    return 0.0


def issues_for_chunk(pcm: np.ndarray) -> list[tuple[str, float]]:
    ratios = band_ratios(pcm)
    found: list[tuple[str, float]] = []
    for issue_type in ("rumble", "mud", "thin", "harsh"):
        score = _score_issue(ratios, issue_type)
        if score >= EQ_SUGGEST_THRESHOLD:
            found.append((issue_type, score))
    return found


def _merge_eq_windows(
    windows: list[tuple[float, float, str, float]],
) -> list[tuple[float, float, str, float]]:
    if not windows:
        return []
    windows = sorted(windows, key=lambda w: (w[0], w[2]))
    merged: list[tuple[float, float, str, float]] = [windows[0]]
    for start, end, issue_type, score in windows[1:]:
        ps, pe, pissue, pscore = merged[-1]
        if issue_type == pissue and start <= pe + 0.25:
            merged[-1] = (ps, max(pe, end), issue_type, max(pscore, score))
        else:
            merged.append((start, end, issue_type, score))
    return merged


def score_sliding_eq_windows(media: Path, duration: float) -> list[tuple[float, float, str, float]]:
    pcm = audio_analysis.extract_pcm_mono(media, 0.0, duration)
    win = int(WINDOW_SEC * ANALYSIS_SAMPLE_RATE)
    step = max(1, int(WINDOW_STEP_SEC * ANALYSIS_SAMPLE_RATE))
    windows: list[tuple[float, float, str, float]] = []
    for offset in range(0, max(1, len(pcm) - win), step):
        chunk = pcm[offset : offset + win]
        start = offset / ANALYSIS_SAMPLE_RATE
        end = min(duration, start + WINDOW_SEC)
        for issue_type, score in issues_for_chunk(chunk):
            windows.append((start, end, issue_type, score))
    return _merge_eq_windows(windows)


def suggest_eq(media: Path) -> list[EqSuggestion]:
    duration = audio_analysis.media_duration(media)
    windows = score_sliding_eq_windows(media, duration)
    suggestions: list[EqSuggestion] = []
    for start, end, issue_type, score in windows:
        if end - start < 0.2:
            continue
        suggestions.append(
            EqSuggestion(
                start=round(start, 3),
                end=round(end, 3),
                issue_type=issue_type,
                severity=_severity(score),
                score=round(score, 3),
                confidence="medium",
                recommendation=ISSUE_RECOMMENDATIONS[issue_type],
            )
        )
    suggestions.sort(key=lambda s: s.score, reverse=True)
    return suggestions


def render_eq_heatmap(
    media: Path,
    suggestions: list[EqSuggestion],
    out_path: Path,
    duration: float | None = None,
) -> None:
    """Reuse NR heatmap layout with EQ issue labels."""
    from avo.audio_analysis import NoiseSuggestion, render_heatmap

    pseudo = [
        NoiseSuggestion(
            start=s.start,
            end=s.end,
            noise_score=s.score,
            suggested_strength_pct=int(s.score * 100),
            confidence=s.confidence,
            reason=s.issue_type,
        )
        for s in suggestions
    ]
    render_heatmap(media, pseudo, out_path, duration=duration)
