"""Noise analysis and restoration suggestions for AVO /avo.sound."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from avo import audio_restoration
from avo.timeline_view import compute_envelope, find_silences, load_font, words_in_range

SUGGEST_THRESHOLD = 0.55
WINDOW_SEC = 2.0
WINDOW_STEP_SEC = 1.0
SILENCE_GAP_SEC = 0.4
ANALYSIS_SAMPLE_RATE = 16000


@dataclass
class NoiseSuggestion:
    start: float
    end: float
    noise_score: float
    suggested_strength_pct: int
    confidence: str
    reason: str = "high_hiss"

    def to_dict(self) -> dict:
        return asdict(self)


def media_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def extract_pcm_mono(path: Path, start: float = 0.0, duration: float | None = None) -> np.ndarray:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav = Path(f.name)
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(path),
        ]
        if duration is not None:
            cmd.extend(["-t", f"{duration:.3f}"])
        cmd.extend(
            [
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(ANALYSIS_SAMPLE_RATE),
                "-c:a",
                "pcm_s16le",
                str(wav),
            ]
        )
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0 or not wav.exists() or wav.stat().st_size == 0:
            raise RuntimeError(f"Could not read audio from {path}")
        with wave.open(str(wav), "rb") as w:
            frames = w.readframes(w.getnframes())
        return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    finally:
        wav.unlink(missing_ok=True)


def _score_from_rms(rms: float, baseline: float) -> float:
    if baseline <= 1e-9:
        baseline = 1e-9
    ratio = rms / baseline
    score = min(1.0, max(0.0, (ratio - 0.35) / 1.2))
    return score


def suggested_pct_from_score(score: float) -> int:
    if score < SUGGEST_THRESHOLD:
        return audio_restoration.ENGINE_DEFAULT_PCT
    if score < 0.65:
        return 50
    if score < 0.75:
        return 60
    if score < 0.85:
        return 70
    return 75


def _merge_windows(windows: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    if not windows:
        return []
    windows = sorted(windows, key=lambda w: w[0])
    merged: list[tuple[float, float, float]] = [windows[0]]
    for start, end, score in windows[1:]:
        prev_start, prev_end, prev_score = merged[-1]
        if start <= prev_end + 0.25:
            merged[-1] = (prev_start, max(prev_end, end), max(prev_score, score))
        else:
            merged.append((start, end, score))
    return merged


def score_from_transcript_gaps(
    media: Path,
    transcript: Path,
    duration: float,
) -> list[tuple[float, float, float]]:
    words = words_in_range(transcript, 0.0, duration)
    gaps = find_silences(words, 0.0, duration, threshold=SILENCE_GAP_SEC)
    if not gaps:
        return []

    pcm = extract_pcm_mono(media, 0.0, duration)
    speech_samples = []
    for w in words:
        if w.get("type") == "spacing":
            continue
        ws = max(0, int(float(w["start"]) * ANALYSIS_SAMPLE_RATE))
        we = min(len(pcm), int(float(w["end"]) * ANALYSIS_SAMPLE_RATE))
        if we > ws:
            speech_samples.append(pcm[ws:we])
    if speech_samples:
        speech_rms = float(np.sqrt(np.mean(np.concatenate(speech_samples) ** 2)))
    else:
        speech_rms = float(np.sqrt(np.mean(pcm ** 2))) or 1e-6

    windows: list[tuple[float, float, float]] = []
    for gap_start, gap_end in gaps:
        gs = int(gap_start * ANALYSIS_SAMPLE_RATE)
        ge = int(gap_end * ANALYSIS_SAMPLE_RATE)
        if ge <= gs:
            continue
        gap_rms = float(np.sqrt(np.mean(pcm[gs:ge] ** 2)))
        score = _score_from_rms(gap_rms, speech_rms)
        if score >= SUGGEST_THRESHOLD:
            windows.append((gap_start, gap_end, score))
    return _merge_windows(windows)


def score_sliding_windows(media: Path, duration: float) -> list[tuple[float, float, float]]:
    pcm = extract_pcm_mono(media, 0.0, duration)
    overall = float(np.sqrt(np.mean(pcm ** 2))) or 1e-6
    win = int(WINDOW_SEC * ANALYSIS_SAMPLE_RATE)
    step = max(1, int(WINDOW_STEP_SEC * ANALYSIS_SAMPLE_RATE))
    windows: list[tuple[float, float, float]] = []
    for offset in range(0, max(1, len(pcm) - win), step):
        chunk = pcm[offset : offset + win]
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        score = _score_from_rms(rms, overall * 0.6)
        if score >= SUGGEST_THRESHOLD:
            start = offset / ANALYSIS_SAMPLE_RATE
            end = min(duration, start + WINDOW_SEC)
            windows.append((start, end, score))
    return _merge_windows(windows)


def suggest_noise_reduction(
    media: Path,
    transcript: Path | None = None,
) -> list[NoiseSuggestion]:
    duration = media_duration(media)
    if transcript and transcript.exists():
        windows = score_from_transcript_gaps(media, transcript, duration)
        confidence = "high"
    else:
        windows = score_sliding_windows(media, duration)
        confidence = "medium"

    suggestions: list[NoiseSuggestion] = []
    for start, end, score in windows:
        if end - start < 0.2:
            continue
        suggestions.append(
            NoiseSuggestion(
                start=round(start, 3),
                end=round(end, 3),
                noise_score=round(score, 3),
                suggested_strength_pct=suggested_pct_from_score(score),
                confidence=confidence if confidence == "high" else ("low" if score < 0.65 else "medium"),
            )
        )
    suggestions.sort(key=lambda s: s.noise_score, reverse=True)
    return suggestions


def render_heatmap(
    media: Path,
    suggestions: list[NoiseSuggestion],
    out_path: Path,
    duration: float | None = None,
) -> None:
    if duration is None:
        duration = media_duration(media)
    env = compute_envelope(media, 0.0, duration, samples=1200)
    width, wave_h = 1920, 220
    legend_h = 80
    height = wave_h + legend_h + 40
    img = Image.new("RGB", (width, height), (18, 18, 22))
    draw = ImageDraw.Draw(img)
    font = load_font(18)
    small = load_font(14)

    # Waveform
    mid = 30 + wave_h // 2
    for i, val in enumerate(env):
        x = int(i / len(env) * (width - 40)) + 20
        h = int(val * (wave_h // 2 - 10))
        draw.line([(x, mid - h), (x, mid + h)], fill=(140, 180, 255))

    # Heat overlays for suggestions
    for sug in suggestions:
        x0 = 20 + int((sug.start / duration) * (width - 40))
        x1 = 20 + int((sug.end / duration) * (width - 40))
        draw.rectangle([x0, 25, x1, 25 + wave_h], fill=(180, 70, 40))
        draw.text((x0, 8), f"{sug.suggested_strength_pct}%", fill=(255, 200, 160), font=small)

    draw.text((20, wave_h + 35), "Noise heatmap — warmer = higher score", fill=(200, 200, 210), font=font)
    draw.text((20, wave_h + 58), "Blue: waveform | Orange bands: suggested NR windows", fill=(140, 140, 150), font=small)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def preview_segment(
    media: Path,
    start: float,
    end: float,
    strength_pct: int,
    out_dir: Path,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = end - start
    before = out_dir / f"preview_{start:.1f}-{end:.1f}_before.wav"
    after = out_dir / f"preview_{start:.1f}-{end:.1f}_after_{strength_pct}pct.wav"
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
    filt = audio_restoration.build_repair_filter(strength_pct)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(before),
            "-af",
            filt,
            str(after),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"before": str(before), "after": str(after)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path, help="Video or audio file")
    parser.add_argument("--suggest-nr", action="store_true", help="Emit noise reduction suggestions JSON")
    parser.add_argument("--transcript", type=Path, help="Word-timed transcript JSON")
    parser.add_argument("--out-dir", type=Path, help="Output directory for artifacts")
    parser.add_argument("--heatmap", action="store_true", help="Write heatmap PNG alongside JSON")
    parser.add_argument("--preview-segment", nargs=2, type=float, metavar=("START", "END"))
    parser.add_argument("--strength-pct", type=int, default=70)
    args = parser.parse_args(argv)

    if not args.media.exists():
        print(f"error: media not found: {args.media}", file=sys.stderr)
        return 1

    out_dir = args.out_dir or Path(".")

    if args.preview_segment:
        start, end = args.preview_segment
        paths = preview_segment(args.media, start, end, args.strength_pct, out_dir)
        print(json.dumps(paths, indent=2))
        return 0

    if not args.suggest_nr:
        parser.error("Specify --suggest-nr or --preview-segment")

    suggestions = suggest_noise_reduction(args.media, args.transcript)
    payload = {
        "media": str(args.media.resolve()),
        "suggestions": [s.to_dict() for s in suggestions],
        "default_strength_pct": audio_restoration.ENGINE_DEFAULT_PCT,
    }
    json_path = out_dir / "noise-reduction-suggestions.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))

    if args.heatmap:
        heatmap_path = out_dir / "noise-reduction-heatmap.png"
        render_heatmap(args.media, suggestions, heatmap_path)
        print(f"heatmap: {heatmap_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
