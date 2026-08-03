from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from avo import audio_analysis


def _write_noisy_wav(path: Path, seconds: float = 3.0, sr: int = 16000) -> None:
    n = int(seconds * sr)
    t = np.linspace(0, seconds, n, endpoint=False)
    signal = 0.02 * np.sin(2 * np.pi * 440 * t)
    noise = 0.15 * np.random.default_rng(42).standard_normal(n)
    pcm = np.clip(signal + noise, -1.0, 1.0)
    ints = (pcm * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(ints.tobytes())


class AudioAnalysisTests(unittest.TestCase):
    def test_sliding_window_suggestions_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "noisy.wav"
            _write_noisy_wav(wav)
            first = audio_analysis.suggest_noise_reduction(wav)
            second = audio_analysis.suggest_noise_reduction(wav)
            self.assertEqual(
                [s.to_dict() for s in first],
                [s.to_dict() for s in second],
            )

    def test_suggestion_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "noisy.wav"
            _write_noisy_wav(wav, seconds=5.0)
            suggestions = audio_analysis.suggest_noise_reduction(wav)
            if suggestions:
                item = suggestions[0].to_dict()
                for key in ("start", "end", "noise_score", "suggested_strength_pct", "confidence"):
                    self.assertIn(key, item)

    def test_score_helpers(self) -> None:
        self.assertEqual(audio_analysis.suggested_pct_from_score(0.4), 35)
        self.assertGreaterEqual(audio_analysis.suggested_pct_from_score(0.9), 70)


if __name__ == "__main__":
    unittest.main()
