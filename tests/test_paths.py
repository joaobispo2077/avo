"""Tests for avo.paths repository layout helpers."""

from __future__ import annotations

import os
import unittest
import unittest.mock
from pathlib import Path

from avo.paths import (
    assert_layout,
    config_dir,
    config_path,
    providers_dir,
    repo_root,
    schema_path,
    schemas_dir,
)


class PathsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_repo_root_from_package(self) -> None:
        self.assertEqual(repo_root(), self.root.resolve())

    def test_repo_root_explicit_start(self) -> None:
        self.assertEqual(repo_root(self.root / "tests"), (self.root / "tests").resolve())

    def test_repo_root_env_override(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"AVO_ROOT": str(self.root)}):
            self.assertEqual(repo_root(), self.root.resolve())

    def test_config_paths_relocated_layout(self) -> None:
        self.assertEqual(config_dir(), self.root / "config")
        self.assertEqual(
            config_path("avo.config.json"),
            self.root / "config" / "avo.config.json",
        )
        self.assertTrue(config_path("avo.config.json").is_file())

    def test_schema_paths_relocated_layout(self) -> None:
        self.assertEqual(schemas_dir(), self.root / "schemas")
        project_schema = schema_path("avo.project.schema.json")
        self.assertEqual(project_schema, self.root / "schemas" / "avo.project.schema.json")
        self.assertTrue(project_schema.is_file())
        edl_schema = schema_path("edl.schema.json")
        self.assertEqual(edl_schema, self.root / "schemas" / "edl.schema.json")
        self.assertTrue(edl_schema.is_file())

    def test_providers_dir(self) -> None:
        self.assertEqual(providers_dir(), self.root / "providers")
        self.assertTrue((providers_dir() / "_template").is_dir())

    def test_assert_layout_passes(self) -> None:
        assert_layout()


if __name__ == "__main__":
    unittest.main()
