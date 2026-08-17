from __future__ import annotations

import json
import unittest

from avo.paths import schema_path
from avo.timeline.contracts import ContractError, validate_document


class TimelineCommonSchemaTests(unittest.TestCase):
    def sample(self) -> dict:
        return {
            "schemaVersion": "1.0.0",
            "artifactType": "cmap",
            "artifactId": "cmap-main",
            "videoId": "video-1",
            "provider": "bishop",
            "timelineDomain": "raw-source",
            "currentRevisionId": None,
            "approvedRevisionId": None,
            "revisions": [],
        }

    def test_schema_exposes_strict_shared_definitions(self) -> None:
        schema = json.loads(
            schema_path("avo.timeline-common.schema.json").read_text(encoding="utf-8")
        )
        self.assertFalse(schema["additionalProperties"])
        for name in (
            "sha256",
            "fingerprint",
            "timebase",
            "timeValue",
            "dependencyRef",
            "diffOperation",
            "evidenceRef",
            "approval",
            "revision",
        ):
            self.assertIn(name, schema["$defs"])

    def test_unknown_envelope_field_is_rejected(self) -> None:
        document = self.sample()
        document["surprise"] = True
        with self.assertRaises(ContractError):
            validate_document(document, "avo.timeline-common.schema.json")

    def test_source_time_requires_source_id(self) -> None:
        schema = "avo.timeline-common.schema.json#/$defs/timeValue"
        value = {
            "ticks": 128,
            "timebase": {"num": 1, "den": 1000},
            "domain": "raw-source",
        }
        with self.assertRaises(ContractError):
            validate_document(value, schema)


if __name__ == "__main__":
    unittest.main()
