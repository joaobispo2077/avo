from __future__ import annotations

import unittest
from copy import deepcopy

from avo.timeline.mapping import (
    MappingError,
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
    @staticmethod
    def _with_repeated_take():
        snapshot = deepcopy(SNAPSHOT)
        repeated = deepcopy(snapshot["segments"][0])
        repeated["segmentId"] = "repeat-a"
        snapshot["segments"].append(repeated)
        return snapshot

    def test_source_point_can_select_its_exact_repeated_occurrence(self):
        snapshot = self._with_repeated_take()
        before = deepcopy(snapshot)
        self.assertEqual(cmap_raw_to_output(snapshot, "cam1", 2000), 1000)
        self.assertEqual(
            cmap_raw_to_output(snapshot, "cam1", 2000, segment_id="a"), 1000
        )
        self.assertEqual(
            cmap_raw_to_output(snapshot, "cam1", 2000, segment_id="repeat-a"), 5000
        )
        self.assertEqual(snapshot, before)

    def test_unknown_or_wrong_source_occurrence_never_falls_back_to_the_first(self):
        snapshot = self._with_repeated_take()
        self.assertIsNone(
            cmap_raw_to_output(snapshot, "cam1", 2000, segment_id="missing")
        )
        self.assertIsNone(
            cmap_raw_to_output(snapshot, "cam2", 1000, segment_id="repeat-a")
        )

    def test_explicit_occurrence_resolves_its_own_native_source_clock(self):
        snapshot = self._with_repeated_take()
        for endpoint in ("in", "out"):
            snapshot["segments"][-1][endpoint]["ticks"] *= 2
            snapshot["segments"][-1][endpoint]["timebase"] = {"num": 1, "den": 2000}
        with self.assertRaisesRegex(MappingError, "ambiguous raw source clock"):
            cmap_raw_to_output(snapshot, "cam1", 2000)
        self.assertEqual(
            cmap_raw_to_output(snapshot, "cam1", 4000, segment_id="repeat-a"), 5000
        )

    def test_contiguous_segment_selection_cannot_be_ignored_for_a_placed_timeline(self):
        with self.assertRaisesRegex(MappingError, "segment|placed"):
            cmap_raw_to_output({"layoutMode": "placed"}, "cam1", 2000, segment_id="a")

    def test_multisource_reorder_round_trip(self) -> None:
        self.assertEqual(cmap_raw_to_output(SNAPSHOT, "cam2", 1000), 2500)
        self.assertEqual(cmap_output_to_raw(SNAPSHOT, 2500), ("cam2", 1000))

    def test_boundary_selects_next_segment(self) -> None:
        self.assertEqual(cmap_output_to_raw(SNAPSHOT, 2000), ("cam2", 500))

    def test_removed_source_point_returns_none(self) -> None:
        self.assertIsNone(cmap_raw_to_output(SNAPSHOT, "cam1", 5000))

    def test_duration_uses_integer_ticks(self) -> None:
        self.assertEqual(cmap_output_duration(SNAPSHOT), 4000)

    def test_output_timebase_comes_from_first_segment_with_mixed_source_rates(self):
        snapshot = deepcopy(SNAPSHOT)
        for endpoint in ("in", "out"):
            value = snapshot["segments"][1][endpoint]
            value["ticks"] *= 2
            value["timebase"] = {"num": 1, "den": 2000}
        self.assertEqual(cmap_output_duration(snapshot), 4000)
        self.assertEqual(cmap_raw_to_output(snapshot, "cam2", 2000), 2500)
        self.assertEqual(cmap_output_to_raw(snapshot, 2500), ("cam2", 2000))

    def test_raw_segment_start_and_end_map_to_exact_output_boundaries(self):
        self.assertEqual(cmap_raw_to_output(SNAPSHOT, "cam2", 500), 2000)
        self.assertEqual(cmap_raw_to_output(SNAPSHOT, "cam2", 1500), 3000)

    def test_third_reordered_segment_accumulates_all_previous_durations(self):
        self.assertEqual(cmap_raw_to_output(SNAPSHOT, "cam1", 500), 3500)
        self.assertEqual(cmap_output_to_raw(SNAPSHOT, 3500), ("cam1", 500))

    def test_last_join_selects_next_source_and_final_endpoint_is_inclusive(self):
        self.assertEqual(cmap_output_to_raw(SNAPSHOT, 3000), ("cam1", 0))
        self.assertEqual(cmap_output_to_raw(SNAPSHOT, 4000), ("cam1", 1000))
        self.assertIsNone(cmap_output_to_raw(SNAPSHOT, 4001))

    def test_raw_half_tick_cannot_be_rounded_into_output_timebase(self) -> None:
        with self.assertRaisesRegex(MappingError, "represented exactly"):
            cmap_raw_to_output(
                SNAPSHOT, "cam1", 2001, raw_timebase={"num": 1, "den": 2000}
            )


if __name__ == "__main__":
    unittest.main()
