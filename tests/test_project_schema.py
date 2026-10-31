"""Project-schema coverage for reusable Shorts defaults."""

from __future__ import annotations

import json
import unittest

from avo.paths import schema_path
from avo.timeline.contracts import ContractError, validate_document
from jsonschema_support import validator_for


class ShortsProjectSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(
            schema_path("avo.project.schema.json").read_text(encoding="utf-8")
        )
        self.validator = validator_for(self.schema)
        self.base = {"provider": "bishop", "rawDir": "/media/raw"}

    def test_optional_shorts_defaults_are_valid(self) -> None:
        document = {
            **self.base,
            "shorts": {
                "requestPath": "edit/shorts/demo/shorts.request.json",
                "defaults": {
                    "speed": {"default": 1.0, "maximum": 1.2},
                    "captionAnchor": "bottom",
                },
            },
        }
        self.assertEqual(list(self.validator.iter_errors(document)), [])

    def test_runtime_batch_state_is_not_allowed_in_project_defaults(self) -> None:
        document = {
            **self.base,
            "shorts": {
                "requestPath": "edit/shorts/demo/shorts.request.json",
                "planHash": "a" * 64,
                "batchState": "building-proofs",
            },
        }
        errors = list(self.validator.iter_errors(document))
        self.assertTrue(errors)
        self.assertIn("Additional properties", errors[0].message)

    def test_optional_watch_policy_is_strict_and_backward_compatible(self) -> None:
        self.assertEqual(list(self.validator.iter_errors(self.base)), [])
        valid = {
            **self.base,
            "watch": {
                "device": "cpu",
                "analysisAttempts": 2,
                "acceptanceCriteria": ["captions remain readable"],
            },
        }
        self.assertEqual(list(self.validator.iter_errors(valid)), [])
        invalid = {**self.base, "watch": {"device": "metal", "topic": "private"}}
        self.assertTrue(list(self.validator.iter_errors(invalid)))

    def test_beat_edit_deliverable_profile_is_valid(self) -> None:
        document = {
            **self.base,
            "deliverable": {"profile": "beat-edit", "aspect": "1:1"},
        }
        self.assertEqual(list(self.validator.iter_errors(document)), [])


class CuttingProjectSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = {"provider": "bishop", "rawDir": "/media/raw"}

    def test_production_validator_resolves_cutting_configuration(self) -> None:
        document = {
            **self.base,
            "cutting": {
                "enabled": True,
                "intensity": "dynamic",
                "guards": {"beforeMs": 120, "afterMs": 180},
            },
        }
        self.assertIs(validate_document(document, "avo.project.schema.json"), document)

    def test_production_validator_keeps_cutting_configuration_strict(self) -> None:
        for cutting, message in [
            ({"enabled": "yes"}, "is not of type 'boolean'"),
            ({"intensity": "invalid"}, "is not one of"),
            ({"guards": {"beforeMs": 119}}, "is less than the minimum"),
            ({"unknown": True}, "Additional properties"),
        ]:
            with self.subTest(cutting=cutting):
                with self.assertRaisesRegex(ContractError, message):
                    validate_document(
                        {**self.base, "cutting": cutting}, "avo.project.schema.json"
                    )


if __name__ == "__main__":
    unittest.main()
