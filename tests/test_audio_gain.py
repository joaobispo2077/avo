from __future__ import annotations

import unittest

from avo import audio_gain


class AudioGainTests(unittest.TestCase):
    def test_boost_db_from_pct_light(self) -> None:
        self.assertAlmostEqual(audio_gain.boost_db_from_pct(15), 1.5, places=1)

    def test_boost_db_from_pct_standard(self) -> None:
        self.assertAlmostEqual(audio_gain.boost_db_from_pct(25), 2.5, places=1)

    def test_boost_db_capped_at_six_db(self) -> None:
        self.assertLessEqual(audio_gain.boost_db_from_pct(100, approved=True), 6.0)

    def test_volume_filter_off_at_zero(self) -> None:
        self.assertEqual(audio_gain.volume_filter(0), "")

    def test_volume_filter_positive(self) -> None:
        filt = audio_gain.volume_filter(25, approved=True)
        self.assertTrue(filt.startswith("volume="))

    def test_suggested_boost_from_score(self) -> None:
        self.assertEqual(audio_gain.suggested_boost_pct_from_score(0.5), 0)
        self.assertEqual(audio_gain.suggested_boost_pct_from_score(0.7), 25)
        self.assertEqual(audio_gain.suggested_boost_pct_from_score(0.9), 60)

    def test_validate_gain_segments_requires_approval_above_40(self) -> None:
        errors = audio_gain.validate_gain_segments(
            {
                "gain_segments": [
                    {
                        "start_in_source": 0.0,
                        "end_in_source": 2.0,
                        "boost_pct": 60,
                    }
                ]
            }
        )
        self.assertTrue(any("approved_by_user" in e for e in errors))

    def test_validate_gain_segments_ok_when_approved(self) -> None:
        errors = audio_gain.validate_gain_segments(
            {
                "gain_segments": [
                    {
                        "start_in_source": 0.0,
                        "end_in_source": 2.0,
                        "boost_pct": 60,
                        "approved_by_user": True,
                    }
                ]
            }
        )
        self.assertEqual(errors, [])

    def test_gain_filter_for_segment(self) -> None:
        edl = {
            "audio": {
                "gain_policy": "level_match_speech",
                "gain_segments": [
                    {
                        "start_in_source": 1.0,
                        "end_in_source": 3.0,
                        "boost_pct": 25,
                        "approved_by_user": True,
                    }
                ],
            }
        }
        filt = audio_gain.gain_filter_for(edl, "main_cam_a", 1.5, 2.5)
        self.assertIn("volume=", filt)

    def test_gain_filter_skips_unapproved_strong_boost(self) -> None:
        edl = {
            "audio": {
                "gain_segments": [
                    {
                        "start_in_source": 0.0,
                        "end_in_source": 5.0,
                        "boost_pct": 60,
                    }
                ],
            }
        }
        filt = audio_gain.gain_filter_for(edl, "main_cam_a", 1.0, 2.0)
        self.assertEqual(filt, "")


if __name__ == "__main__":
    unittest.main()
