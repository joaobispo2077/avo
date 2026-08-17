from __future__ import annotations

import unittest

from avo.timeline.projection import project_cmap_to_edl


class TimelineProjectionTests(unittest.TestCase):
    def test_projection_preserves_order_and_marks_derived_lineage(self) -> None:
        artifact = {
            "artifactType": "cmap",
            "artifactId": "main",
            "currentRevisionId": "r1",
            "approvedRevisionId": "r1",
            "revisions": [
                {
                    "revisionId": "r1",
                    "contentHash": "a" * 64,
                    "snapshot": {
                        "sources": [
                            {"sourceId": "a", "locator": "raw/a.mp4"},
                            {"sourceId": "b", "locator": "raw/b.mp4"},
                        ],
                        "segments": [
                            {
                                "segmentId": "s2",
                                "sourceId": "b",
                                "in": {
                                    "ticks": 500,
                                    "timebase": {"num": 1, "den": 1000},
                                },
                                "out": {
                                    "ticks": 1500,
                                    "timebase": {"num": 1, "den": 1000},
                                },
                                "storySectionId": "middle",
                            },
                            {
                                "segmentId": "s1",
                                "sourceId": "a",
                                "in": {"ticks": 0, "timebase": {"num": 1, "den": 1000}},
                                "out": {
                                    "ticks": 2000,
                                    "timebase": {"num": 1, "den": 1000},
                                },
                                "storySectionId": "end",
                            },
                        ],
                    },
                }
            ],
        }
        edl = project_cmap_to_edl(artifact)
        self.assertEqual([r["source"] for r in edl["ranges"]], ["b", "a"])
        self.assertEqual(edl["sources"]["a"], "raw/a.mp4")
        self.assertEqual(edl["story_map_approval"], "approved")
        self.assertEqual(edl["timeline_projection"]["cmapRevisionId"], "r1")
        self.assertFalse(edl["timeline_projection"]["canonical"])


if __name__ == "__main__":
    unittest.main()
