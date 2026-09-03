from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from avo.settings import (
    SettingsError,
    redact_path,
    resolve_path_setting,
    resolve_scoped_settings,
)


class ScopedSettingsTests(unittest.TestCase):
    def test_field_precedence_arrays_and_provenance(self) -> None:
        result = resolve_scoped_settings(
            defaults={"device": "auto", "criteria": [], "nested": {"a": 1}},
            scopes=[
                ("global", {"device": "cpu", "criteria": ["global"]}),
                ("provider", {"nested": {"b": 2}}),
                ("registry", {"criteria": ["registry"]}),
                ("project", {"device": "cuda:1"}),
                ("invocation", {"criteria": ["cli"]}),
            ],
        )
        self.assertEqual(result.values["device"], "cuda:1")
        self.assertEqual(result.values["criteria"], ["cli"])
        self.assertEqual(result.values["nested"], {"a": 1, "b": 2})
        self.assertEqual(result.sources["device"], "project")
        self.assertEqual(result.sources["criteria"], "invocation")
        self.assertEqual(result.sources["nested.a"], "default")
        self.assertEqual(result.sources["nested.b"], "provider")
        self.assertFalse(result.setting("nested.a").explicit)
        self.assertTrue(result.setting("nested.b").explicit)

    def test_hash_is_stable_across_input_key_order(self) -> None:
        left = resolve_scoped_settings(defaults={"a": 1, "b": 2}, scopes=[])
        right = resolve_scoped_settings(defaults={"b": 2, "a": 1}, scopes=[])
        self.assertEqual(left.policy_hash, right.policy_hash)

    def test_hash_includes_provenance_without_cross_resolution_mutation(self) -> None:
        global_value = resolve_scoped_settings(defaults={"device": "auto"}, scopes=[])
        project_value = resolve_scoped_settings(
            defaults={"device": "cpu"}, scopes=[("project", {"device": "auto"})]
        )
        self.assertEqual(global_value.values, project_value.values)
        self.assertNotEqual(global_value.policy_hash, project_value.policy_hash)

    def test_path_resolution_containment_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp).resolve()
            resolved = resolve_path_setting("edit/watch", base=raw, contain=True)
            self.assertEqual(resolved, raw / "edit" / "watch")
            self.assertEqual(redact_path(resolved, base=raw), "<rawDir>/edit/watch")
            with self.assertRaises(SettingsError):
                resolve_path_setting("../private", base=raw, contain=True)


if __name__ == "__main__":
    unittest.main()
