from __future__ import annotations

import unittest

from avo.timeline.contracts import ContractError, validate_document

SHA = "a" * 64


def document():
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "bmap",
        "artifactId": "beats",
        "videoId": "v",
        "provider": "bishop",
        "timelineDomain": "cmap-output",
        "currentRevisionId": "r1",
        "approvedRevisionId": None,
        "revisions": [
            {
                "revisionId": "r1",
                "parentRevisionId": None,
                "createdAt": "2026-08-13T00:00:00Z",
                "actor": "agent",
                "reason": "beats",
                "snapshot": {
                    "basis": {
                        "artifactType": "cmap",
                        "artifactId": "main",
                        "revisionId": "c1",
                        "sha256": SHA,
                        "outputSha256": "b" * 64,
                        "state": "valid",
                    },
                    "cues": [
                        {
                            "cueId": "cue-one",
                            "start": {
                                "ticks": 100,
                                "timebase": {"num": 1, "den": 1000},
                                "domain": "cmap-output",
                            },
                            "end": {
                                "ticks": 200,
                                "timebase": {"num": 1, "den": 1000},
                                "domain": "cmap-output",
                            },
                            "kind": "text",
                            "contentRef": {"text": "hello"},
                            "targetLayerId": "graphics",
                            "intent": "clarify",
                            "reason": "spoken point",
                            "reviewState": "pending",
                            "rebaseHints": {
                                "rawAnchors": [],
                                "transcriptSpanSha256": "c" * 64,
                            },
                        }
                    ],
                },
                "diff": [],
                "dependencies": [],
                "contentHash": "c" * 64,
                "evidence": [],
                "state": "draft",
            }
        ],
        "decisions": [],
    }


class BMapSchemaTests(unittest.TestCase):
    def test_valid(self):
        validate_document(document(), "avo.bmap.schema.json")

    def test_rejects_raw_domain(self):
        value = document()
        value["revisions"][0]["snapshot"]["cues"][0]["start"]["domain"] = "raw-source"
        with self.assertRaises(ContractError):
            validate_document(value, "avo.bmap.schema.json")

    def test_rejects_source_id_on_output_time(self):
        value = document()
        value["revisions"][0]["snapshot"]["cues"][0]["start"]["sourceId"] = "camera"
        with self.assertRaises(ContractError):
            validate_document(value, "avo.bmap.schema.json")

    def test_rejects_bad_asset_fingerprint(self):
        value = document()
        value["revisions"][0]["snapshot"]["cues"][0]["assetRef"] = {
            "locator": "image.png",
            "sha256": "bad",
            "sizeBytes": 3,
        }
        with self.assertRaises(ContractError):
            validate_document(value, "avo.bmap.schema.json")
