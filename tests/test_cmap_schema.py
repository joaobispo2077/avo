from __future__ import annotations

import unittest

from avo.timeline.contracts import ContractError, validate_document


SHA = "a" * 64


def cmap_document() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "cmap",
        "artifactId": "main",
        "videoId": "video-1",
        "provider": "bishop",
        "timelineDomain": "raw-source",
        "currentRevisionId": "r0001",
        "approvedRevisionId": None,
        "revisions": [{
            "revisionId": "r0001", "parentRevisionId": None,
            "createdAt": "2026-08-13T00:00:00Z", "actor": "agent",
            "reason": "initial cut",
            "snapshot": {
                "sources": [{"sourceId": "cam", "kind": "raw", "fingerprint": {"sha256": SHA, "sizeBytes": 10}, "locator": "raw/cam.mp4"}],
                "segments": [{
                    "segmentId": "s1", "sourceId": "cam",
                    "in": {"ticks": 0, "timebase": {"num": 1, "den": 1000}, "domain": "raw-source", "sourceId": "cam"},
                    "out": {"ticks": 1000, "timebase": {"num": 1, "den": 1000}, "domain": "raw-source", "sourceId": "cam"},
                    "storySectionId": "intro", "reason": "keep promise",
                }],
            },
            "diff": [], "dependencies": [], "contentHash": "b" * 64,
            "evidence": [], "state": "draft",
        }],
    }


class CMapSchemaTests(unittest.TestCase):
    def test_raw_cmap_is_valid(self) -> None:
        self.assertEqual(validate_document(cmap_document(), "avo.cmap.schema.json")["artifactType"], "cmap")

    def test_derived_source_kind_is_rejected(self) -> None:
        document = cmap_document()
        document["revisions"][0]["snapshot"]["sources"][0]["kind"] = "trimmed"
        with self.assertRaises(ContractError):
            validate_document(document, "avo.cmap.schema.json")

    def test_segment_requires_stable_id_and_reason(self) -> None:
        document = cmap_document()
        del document["revisions"][0]["snapshot"]["segments"][0]["segmentId"]
        with self.assertRaises(ContractError):
            validate_document(document, "avo.cmap.schema.json")


if __name__ == "__main__":
    unittest.main()
