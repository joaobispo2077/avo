from __future__ import annotations

import unittest

from avo import audio_restoration


class AudioRestorationTests(unittest.TestCase):
    def test_standard_pct_matches_production_afftdn(self) -> None:
        chain = audio_restoration.build_repair_filter(35)
        self.assertIn("afftdn=nr=8.00:nf=-35.0:tn=1", chain)
        self.assertIn("highpass=f=90", chain)

    def test_zero_omits_afftdn(self) -> None:
        chain = audio_restoration.build_repair_filter(0)
        self.assertNotIn("afftdn", chain)
        self.assertIn("highpass", chain)

    def test_cap_at_100(self) -> None:
        nr, nf = audio_restoration.afftdn_params(100)
        assert nr is not None
        self.assertLessEqual(nr, 22.0)

    def test_presets_resolve(self) -> None:
        self.assertEqual(audio_restoration.preset_to_pct("standard"), 35)
        self.assertEqual(audio_restoration.preset_to_pct("strong"), 70)

    def test_segment_overlap_uses_max_strength(self) -> None:
        edl = {
            "audio": {
                "noise_reduction_policy": "conservative_speech_first",
                "restoration_default_pct": 35,
                "restoration_segments": [
                    {
                        "start_in_source": 10.0,
                        "end_in_source": 20.0,
                        "strength_pct": 70,
                        "approved_by_user": True,
                    }
                ],
            }
        }
        pct = audio_restoration.strength_for_source_range(edl, "main", 12.0, 18.0)
        self.assertEqual(pct, 70)
        pct_outside = audio_restoration.strength_for_source_range(edl, "main", 0.0, 5.0)
        self.assertEqual(pct_outside, 35)

    def test_non_main_source_skips_restoration(self) -> None:
        edl = {"audio": {"noise_reduction_policy": "conservative_speech_first"}}
        self.assertEqual(
            audio_restoration.audio_repair_filter_for(edl, "broll", 0.0, 10.0),
            "",
        )

    def test_overlap_validation_errors(self) -> None:
        audio = {
            "restoration_segments": [
                {
                    "start_in_source": 1.0,
                    "end_in_source": 5.0,
                    "strength_pct": 60,
                    "approved_by_user": True,
                },
                {
                    "start_in_source": 4.0,
                    "end_in_source": 8.0,
                    "strength_pct": 70,
                    "approved_by_user": True,
                },
            ]
        }
        errors = audio_restoration.validate_restoration_segments(audio)
        self.assertTrue(any("overlap" in e for e in errors))

    def test_high_strength_requires_approval(self) -> None:
        audio = {
            "restoration_segments": [
                {"start_in_source": 1.0, "end_in_source": 5.0, "strength_pct": 70}
            ]
        }
        errors = audio_restoration.validate_restoration_segments(audio)
        self.assertTrue(any("approved_by_user" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
