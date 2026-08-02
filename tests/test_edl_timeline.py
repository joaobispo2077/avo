from __future__ import annotations

import unittest

from avo.edl_timeline import (
    output_duration,
    output_to_source,
    parse_ranges,
    remap_timed_items,
    source_to_output,
    verify_timed_items,
)


def switch_ranges() -> list:
    return parse_ranges(
        {
            "ranges": [
                {"source": "main", "start": 0.53, "end": 106.65},
                {"source": "main", "start": 199.85, "end": 485.0},
                {"source": "main", "start": 508.0, "end": 538.1},
                {"source": "main", "start": 563.5, "end": 748.95},
                {"source": "main", "start": 765.85, "end": 778.3},
                {"source": "main", "start": 812.65, "end": 1048.25},
            ]
        }
    )


class EdlTimelineTests(unittest.TestCase):
    def test_fetch_cut_shifts_later_source_times(self) -> None:
        ranges = switch_ranges()
        self.assertAlmostEqual(source_to_output(ranges, 476.73), 383.0, places=2)
        self.assertAlmostEqual(source_to_output(ranges, 819.43), 626.05, places=2)

    def test_privacy_cut_maps_user_b_time_back_to_source(self) -> None:
        ranges = switch_ranges()
        broken = parse_ranges(
            {
                "ranges": [
                    {"source": "main", "start": 0.53, "end": 106.65},
                    {"source": "main", "start": 199.85, "end": 485.0},
                    {"source": "main", "start": 508.0, "end": 538.1},
                    {"source": "main", "start": 563.5, "end": 630.0},
                    {"source": "main", "start": 646.0, "end": 778.3},
                    {"source": "main", "start": 812.65, "end": 1048.25},
                ]
            }
        )
        self.assertAlmostEqual(output_to_source(broken, 591.0), 749.13, places=1)
        self.assertAlmostEqual(output_to_source(broken, 607.0), 765.13, places=1)

    def test_remap_overlays_from_source_anchors(self) -> None:
        edl = {
            "ranges": [
                {"source": "main", "start": 0.53, "end": 106.65},
                {"source": "main", "start": 199.85, "end": 485.0},
                {"source": "main", "start": 508.0, "end": 538.1},
                {"source": "main", "start": 563.5, "end": 731.65},
                {"source": "main", "start": 749.38, "end": 778.3},
                {"source": "main", "start": 812.65, "end": 1048.25},
            ],
            "overlays": [
                {
                    "file": "weight.mov",
                    "anchor_in_source": 476.73,
                    "start_in_output": 999.0,
                    "duration": 5.0,
                    "motion_brief_id": "weight",
                }
            ],
        }
        remapped = remap_timed_items(edl)["overlays"][0]
        self.assertAlmostEqual(remapped["start_in_output"], 383.0, places=2)
        edl["overlays"][0]["start_in_output"] = remapped["start_in_output"]
        self.assertEqual(verify_timed_items(edl), [])

    def test_verify_catches_stale_output_time(self) -> None:
        edl = {
            "ranges": [
                {"source": "main", "start": 0.0, "end": 10.0},
            ],
            "overlays": [
                {
                    "file": "a.mov",
                    "anchor_in_source": 5.0,
                    "start_in_output": 8.0,
                    "duration": 1.0,
                    "motion_brief_id": "a",
                }
            ],
        }
        errors = verify_timed_items(edl)
        self.assertEqual(len(errors), 1)
        self.assertIn("start_in_output", errors[0])

    def test_output_duration(self) -> None:
        self.assertAlmostEqual(output_duration(switch_ranges()), 854.87, places=1)


if __name__ == "__main__":
    unittest.main()
