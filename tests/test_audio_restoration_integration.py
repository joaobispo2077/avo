from __future__ import annotations

import unittest

from avo import audio_restoration
from avo import render


class AudioRestorationIntegrationTests(unittest.TestCase):
    def test_render_delegates_standard_chain(self) -> None:
        edl = {"audio": {"noise_reduction_policy": "conservative_speech_first"}}
        chain = render.audio_repair_filter_for(edl, "main", 0.0, 10.0)
        self.assertIn("afftdn=nr=8.00", chain)

    def test_render_uses_segment_strength(self) -> None:
        edl = {
            "audio": {
                "noise_reduction_policy": "conservative_speech_first",
                "restoration_default_pct": 35,
                "restoration_segments": [
                    {
                        "start_in_source": 5.0,
                        "end_in_source": 15.0,
                        "strength_pct": 70,
                        "approved_by_user": True,
                    }
                ],
            }
        }
        chain = render.audio_repair_filter_for(edl, "main", 8.0, 12.0)
        self.assertIn("afftdn=nr=16.00", chain)

    def test_backward_compat_without_new_fields(self) -> None:
        edl = {"audio": {"noise_reduction_policy": "conservative_speech_first"}}
        expected = audio_restoration.build_repair_filter(35)
        self.assertEqual(render.audio_repair_filter_for(edl, "main"), expected)


if __name__ == "__main__":
    unittest.main()
