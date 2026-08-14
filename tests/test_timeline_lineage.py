from __future__ import annotations

import unittest

from avo.timeline.lineage import LineageError, validate_cmap_snapshot


SHA = "a" * 64


def snapshot(kind: str = "raw") -> dict:
    return {
        "sources": [{"sourceId": "cam", "kind": kind, "fingerprint": {"sha256": SHA, "sizeBytes": 1}}],
        "segments": [{
            "segmentId": "s1", "sourceId": "cam",
            "in": {"ticks": 0, "timebase": {"num": 1, "den": 1000}, "domain": "raw-source", "sourceId": "cam"},
            "out": {"ticks": 1, "timebase": {"num": 1, "den": 1000}, "domain": "raw-source", "sourceId": "cam"},
            "reason": "keep",
        }],
    }


class TimelineLineageTests(unittest.TestCase):
    def test_raw_snapshot_passes(self) -> None:
        validate_cmap_snapshot(snapshot())

    def test_derived_bases_are_rejected(self) -> None:
        for kind in ("proxy", "trimmed", "synchronized", "rendered"):
            with self.subTest(kind=kind), self.assertRaises(LineageError):
                validate_cmap_snapshot(snapshot(kind))

    def test_source_id_and_positive_range_are_required(self) -> None:
        value = snapshot()
        value["segments"][0]["out"]["ticks"] = 0
        with self.assertRaises(LineageError):
            validate_cmap_snapshot(value)


if __name__ == "__main__":
    unittest.main()
