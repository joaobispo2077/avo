from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from avo import audio_audit


class AudioAuditTests(unittest.TestCase):
    def test_build_audit_report_structure(self) -> None:
        media = Path("sample.mp4")
        nr = audio_audit.audio_analysis.NoiseSuggestion(
            start=1.0,
            end=2.0,
            noise_score=0.8,
            suggested_strength_pct=70,
            confidence="high",
        )
        eq = audio_audit.audio_eq.EqSuggestion(
            start=3.0,
            end=4.0,
            issue_type="harsh",
            severity="medium",
            score=0.7,
            confidence="medium",
            recommendation="Tame 5–8 kHz",
        )
        gain = audio_audit.audio_gain.GainSuggestion(
            start=5.0,
            end=6.0,
            quiet_score=0.75,
            suggested_boost_pct=25,
            confidence="high",
        )
        profile = audio_audit.loudness_profiles.resolve_loudness_profile(project={})

        with (
            mock.patch(
                "avo.audio_audit.loudness_profiles.measure_loudness",
                return_value={"integrated_lufs": -19.0, "true_peak_dbtp": -2.0, "lra_lu": 8.0},
            ),
            mock.patch(
                "avo.audio_audit.loudness_profiles.compare_measurement",
                return_value={
                    "integrated_lufs": -19.0,
                    "target_integrated_lufs": -16.0,
                    "within_target": False,
                },
            ),
            mock.patch("avo.audio_audit.loudness_profiles.nr_loudness_warning", return_value=None),
            mock.patch(
                "avo.audio_audit.loudness_profiles.resolve_loudness_profile",
                return_value=profile,
            ),
            mock.patch(
                "avo.audio_audit.audio_analysis.suggest_noise_reduction",
                return_value=[nr],
            ),
            mock.patch("avo.audio_audit.audio_eq.suggest_eq", return_value=[eq]),
            mock.patch("avo.audio_audit.audio_gain.suggest_gain", return_value=[gain]),
        ):
            report = audio_audit.build_audit_report(media)

        self.assertTrue(report["read_only"])
        self.assertIn("loudness", report)
        self.assertEqual(len(report["noise_reduction"]["suggestions"]), 1)
        self.assertEqual(report["eq"]["suggestions"][0]["issue_type"], "harsh")
        self.assertEqual(report["gain"]["suggestions"][0]["suggested_boost_pct"], 25)
        self.assertTrue(any("LUFS" in w for w in report["warnings"]))

    def test_strict_tolerance_constant(self) -> None:
        self.assertEqual(audio_audit.STRICT_LU_TOLERANCE, 2.0)


if __name__ == "__main__":
    unittest.main()
