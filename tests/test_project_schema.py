"""Project-schema coverage for reusable Shorts defaults."""

from __future__ import annotations

import json
import unittest

from jsonschema import Draft202012Validator

from avo.paths import schema_path


class ShortsProjectSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(
            schema_path("avo.project.schema.json").read_text(encoding="utf-8")
        )
        self.validator = Draft202012Validator(self.schema)
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


if __name__ == "__main__":
    unittest.main()
