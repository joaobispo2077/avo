from __future__ import annotations

import unittest

from avo.timeline.projection import ProjectionError, project_cmap_to_edl


class TimelineProjectionTests(unittest.TestCase):
    @staticmethod
    def _artifact_with_sources(sources: list[dict]) -> dict:
        return {
            "artifactType": "cmap",
            "artifactId": "main",
            "currentRevisionId": "r1",
            "approvedRevisionId": None,
            "revisions": [
                {
                    "revisionId": "r1",
                    "contentHash": "c" * 64,
                    "snapshot": {
                        "sources": sources,
                        "segments": [
                            {
                                "segmentId": "s1",
                                "sourceId": sources[0]["sourceId"],
                                "in": {
                                    "ticks": 0,
                                    "timebase": {"num": 1, "den": 1000},
                                },
                                "out": {
                                    "ticks": 1000,
                                    "timebase": {"num": 1, "den": 1000},
                                },
                            }
                        ],
                    },
                }
            ],
        }

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
        self.assertNotIn("audio", edl)

    def test_projection_copies_source_audio_stream(self) -> None:
        artifact = self._artifact_with_sources(
            [
                {
                    "sourceId": "cam",
                    "streamMetadata": {
                        "audioStream": "a:1",
                        "dialogueChannel": "left",
                    },
                }
            ]
        )
        edl = project_cmap_to_edl(artifact)
        self.assertEqual(edl["audio"]["main_source_stream"], "a:1")
        self.assertEqual(edl["audio"]["dialogue_channel"], "left")

    def test_projection_selects_complete_audio_metadata_independent_of_order(
        self,
    ) -> None:
        complete = {
            "sourceId": "dialogue",
            "streamMetadata": {
                "audioStream": "a:1",
                "dialogueChannel": "right",
            },
        }
        undeclared = {"sourceId": "silent"}

        first = project_cmap_to_edl(self._artifact_with_sources([complete, undeclared]))
        last = project_cmap_to_edl(self._artifact_with_sources([undeclared, complete]))

        self.assertEqual(first["audio"], last["audio"])
        self.assertEqual(
            first["audio"],
            {"main_source_stream": "a:1", "dialogue_channel": "right"},
        )

    def test_projection_rejects_partial_audio_metadata(self) -> None:
        artifact = self._artifact_with_sources(
            [
                {
                    "sourceId": "camera",
                    "streamMetadata": {"audioStream": "a:1"},
                },
                {
                    "sourceId": "recorder",
                    "streamMetadata": {"dialogueChannel": "left"},
                },
            ]
        )

        with self.assertRaisesRegex(
            ProjectionError,
            r"incomplete audio metadata.*camera.*dialogueChannel.*recorder.*audioStream",
        ):
            project_cmap_to_edl(artifact)

    def test_projection_rejects_conflicting_complete_audio_metadata(self) -> None:
        artifact = self._artifact_with_sources(
            [
                {
                    "sourceId": "camera",
                    "streamMetadata": {
                        "audioStream": "a:0",
                        "dialogueChannel": "left",
                    },
                },
                {
                    "sourceId": "recorder",
                    "streamMetadata": {
                        "audioStream": "a:1",
                        "dialogueChannel": "right",
                    },
                },
            ]
        )

        with self.assertRaisesRegex(
            ProjectionError, r"conflicting audio metadata.*camera.*recorder"
        ):
            project_cmap_to_edl(artifact)


if __name__ == "__main__":
    unittest.main()
