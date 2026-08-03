from __future__ import annotations

import unittest

import numpy as np

from avo import audio_eq
from avo.audio_eq import ANALYSIS_SAMPLE_RATE, band_ratios, issues_for_chunk


class AudioEqTests(unittest.TestCase):
    def test_band_ratios_detect_rumble(self) -> None:
        sr = ANALYSIS_SAMPLE_RATE
        t = np.arange(sr, dtype=np.float32) / sr
        low = np.sin(2 * np.pi * 60 * t).astype(np.float32) * 0.8
        speech = np.sin(2 * np.pi * 1000 * t).astype(np.float32) * 0.05
        pcm = low + speech
        ratios = band_ratios(pcm, sr)
        self.assertGreater(ratios["rumble"], ratios["speech"])

    def test_mud_issue_on_boxy_signal(self) -> None:
        sr = ANALYSIS_SAMPLE_RATE
        t = np.arange(sr, dtype=np.float32) / sr
        mud = np.sin(2 * np.pi * 280 * t).astype(np.float32) * 0.9
        speech = np.sin(2 * np.pi * 2000 * t).astype(np.float32) * 0.15
        issues = issues_for_chunk(mud + speech)
        types = {issue for issue, _ in issues}
        self.assertIn("mud", types)

    def test_harsh_issue_on_bright_signal(self) -> None:
        sr = ANALYSIS_SAMPLE_RATE
        t = np.arange(sr, dtype=np.float32) / sr
        harsh = np.sin(2 * np.pi * 6500 * t).astype(np.float32) * 0.85
        speech = np.sin(2 * np.pi * 1500 * t).astype(np.float32) * 0.2
        issues = issues_for_chunk(harsh + speech)
        types = {issue for issue, _ in issues}
        self.assertIn("harsh", types)

    def test_eq_suggestion_dataclass(self) -> None:
        sug = audio_eq.EqSuggestion(
            start=1.0,
            end=2.0,
            issue_type="mud",
            severity="medium",
            score=0.7,
            confidence="medium",
            recommendation="Cut 250 Hz",
        )
        payload = sug.to_dict()
        self.assertEqual(payload["issue_type"], "mud")
        self.assertEqual(payload["severity"], "medium")


if __name__ == "__main__":
    unittest.main()
