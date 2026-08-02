from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from avo import render


class OverlayCompositeTests(unittest.TestCase):
    def test_overlay_filter_shifts_and_bounds_each_alpha_input(self) -> None:
        overlays = [
            {
                "start_in_output": 3.5,
                "duration": 1.25,
                "motion_brief_id": "transfer-direction",
            }
        ]
        parts, output = render.build_overlay_filter_parts(overlays)
        graph = ";".join(parts)
        self.assertEqual(output, "[v1]")
        self.assertIn("format=yuva420p", graph)
        self.assertIn("setpts=PTS-STARTPTS+3.5/TB", graph)
        self.assertIn("between(t,3.500,4.750)", graph)

    def test_caption_filter_is_appended_after_overlay(self) -> None:
        parts, current = render.build_overlay_filter_parts(
            [
                {
                    "start_in_output": 1,
                    "duration": 1,
                    "motion_brief_id": "transfer-direction",
                }
            ]
        )
        parts.append(render.build_subtitle_filter(current, Path("caption-burn-in.srt")))
        self.assertTrue(parts[-1].startswith("[v1]subtitles="))
        self.assertIn("[outv]", parts[-1])

    def test_many_overlays_preserve_order_and_have_separate_windows(self) -> None:
        overlays = [
            {"start_in_output": 0, "duration": 1, "motion_brief_id": "price"},
            {"start_in_output": 2, "duration": 1.5, "motion_brief_id": "value"},
            {"start_in_output": 5, "duration": 2, "motion_brief_id": "summary"},
        ]
        parts, output = render.build_overlay_filter_parts(overlays)
        graph = ";".join(parts)
        self.assertEqual(output, "[v3]")
        self.assertIn("[0:v][a1]overlay=enable='between(t,0.000,1.000)'[v1]", graph)
        self.assertIn("[v1][a2]overlay=enable='between(t,2.000,3.500)'[v2]", graph)
        self.assertIn("[v2][a3]overlay=enable='between(t,5.000,7.000)'[v3]", graph)

    def test_visual_subtitles_disabled_means_no_subtitle_filter(self) -> None:
        edl = {"caption_policy": {"visual_subtitles": False}, "caption_burn_in": None}
        self.assertFalse(render.visual_subtitles_enabled(edl))


if __name__ == "__main__":
    unittest.main()

