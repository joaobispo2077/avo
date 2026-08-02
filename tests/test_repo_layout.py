"""Release-blocking checks for the refactored repository layout."""

from __future__ import annotations

import unittest
from pathlib import Path

from avo.paths import config_path, repo_root, schema_path


class RepoLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = repo_root()

    def test_config_manifests_live_under_config(self) -> None:
        for name in (
            "avo.config.json",
            "avo.dependencies.json",
            "avo.model-catalog.json",
            "avo.model-catalog.schema.json",
        ):
            path = config_path(name)
            self.assertEqual(path.parent, self.root / "config", msg=name)
            self.assertTrue(path.is_file(), msg=name)

    def test_schemas_live_under_schemas(self) -> None:
        for name in ("avo.project.schema.json", "edl.schema.json"):
            path = schema_path(name)
            self.assertEqual(path.parent, self.root / "schemas", msg=name)
            self.assertTrue(path.is_file(), msg=name)

    def test_no_duplicate_root_manifests(self) -> None:
        for name in (
            "avo.config.json",
            "avo.dependencies.json",
            "avo.model-catalog.json",
            "avo.project.schema.json",
        ):
            self.assertFalse((self.root / name).is_file(), msg=f"legacy root file: {name}")


if __name__ == "__main__":
    unittest.main()
