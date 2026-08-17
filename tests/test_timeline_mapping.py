from __future__ import annotations

import unittest

from avo.timeline.mapping import (
    cmap_output_duration,
    cmap_output_to_raw,
    cmap_raw_to_output,
)


def tv(ticks: int, source: str) -> dict:
    return {
        "ticks": ticks,
        "timebase": {"num": 1, "den": 1000},
        "domain": "raw-source",
        "sourceId": source,
    }


SNAPSHOT = {
    "sources": [],
    "segments": [
        {
            "segmentId": "a",
            "sourceId": "cam1",
            "in": tv(1000, "cam1"),
            "out": tv(3000, "cam1"),
            "reason": "a",
        },
        {
            "segmentId": "b",
            "sourceId": "cam2",
            "in": tv(500, "cam2"),
            "out": tv(1500, "cam2"),
            "reason": "b",
        },
        {
            "segmentId": "c",
            "sourceId": "cam1",
            "in": tv(0, "cam1"),
            "out": tv(1000, "cam1"),
            "reason": "reorder",
        },
    ],
}


class TimelineMappingTests(unittest.TestCase):
    def test_multisource_reorder_round_trip(self) -> None:
        self.assertEqual(cmap_raw_to_output(SNAPSHOT, "cam2", 1000), 2500)
        self.assertEqual(cmap_output_to_raw(SNAPSHOT, 2500), ("cam2", 1000))

    def test_boundary_selects_next_segment(self) -> None:
        self.assertEqual(cmap_output_to_raw(SNAPSHOT, 2000), ("cam2", 500))

    def test_removed_source_point_returns_none(self) -> None:
        self.assertIsNone(cmap_raw_to_output(SNAPSHOT, "cam1", 5000))

    def test_duration_uses_integer_ticks(self) -> None:
        self.assertEqual(cmap_output_duration(SNAPSHOT), 4000)


if __name__ == "__main__":
    unittest.main()
