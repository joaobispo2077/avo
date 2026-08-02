from __future__ import annotations

import unittest

from avo import render


class BoilOverlayIntegrationTests(unittest.TestCase):
    """Validate boil overlay EDL entries use the standard alpha compositor path."""

    def test_boil_overlay_webm_uses_alpha_chain(self) -> None:
        overlays = [
            {
                "file": "edit/animations/slot_boil-callout/render.webm",
                "start_in_output": 12.5,
                "duration": 2.5,
                "motion_brief_id": "boil-callout",
                "anchor_in_source": 45.0,
            }
        ]
        parts, output = render.build_overlay_filter_parts(overlays)
        graph = ";".join(parts)
        self.assertEqual(output, "[v1]")
        self.assertIn("format=yuva420p", graph)
        self.assertIn("trim=duration=2.500", graph)
        self.assertIn("setpts=PTS-STARTPTS+12.5/TB", graph)
        self.assertIn("between(t,12.500,15.000)", graph)

    def test_boil_overlay_with_captions_last(self) -> None:
        from pathlib import Path

        overlays = [
            {
                "start_in_output": 1.0,
                "duration": 2.0,
                "motion_brief_id": "boil-sticker",
            }
        ]
        parts, current = render.build_overlay_filter_parts(overlays)
        parts.append(render.build_subtitle_filter(current, Path("caption-burn-in.srt")))
        self.assertTrue(parts[-1].startswith("[v1]subtitles="))
        self.assertIn("[outv]", parts[-1])

    def test_multiple_boil_slots_sequential_overlay(self) -> None:
        overlays = [
            {"start_in_output": 0.5, "duration": 1.5, "motion_brief_id": "boil-a"},
            {"start_in_output": 4.0, "duration": 2.0, "motion_brief_id": "boil-b"},
        ]
        parts, output = render.build_overlay_filter_parts(overlays)
        graph = ";".join(parts)
        self.assertEqual(output, "[v2]")
        self.assertIn("between(t,0.500,2.000)", graph)
        self.assertIn("between(t,4.000,6.000)", graph)


if __name__ == "__main__":
    unittest.main()
