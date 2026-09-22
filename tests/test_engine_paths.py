"""TDD: frozen vs checkout path resolution (FR-4, FR-10).

Clone `repo_root()` stays the pyproject parent. A fake PyInstaller layout
(`sys.frozen` + `sys._MEIPASS`) must find bundled `config/` and `schemas/`
without walking to a checkout. `AVO_ROOT` still wins. Gate 1 engine mode
must not FAIL only because `src/avo/transcribe.py` is missing.

In-process only — no freeze zip, no `~/.avo/bin/avo`. Red until aeb-013.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from avo.paths import config_path, repo_root, schema_path
from avo.validate_dependencies import run_checks

CHECKOUT = Path(__file__).resolve().parents[1]
_ENGINE_SPEC = {
    "required": True,
    "kind": "python-project",
    "manifest": "pyproject.toml",
    "helpers": ["src/avo/transcribe.py"],
}


def _write_bundle(root: Path) -> Path:
    """Minimal engine prefix: bundled manifests, no clone markers."""
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    (root / "config" / "avo.config.json").write_text('{"jobs": {}}\n', encoding="utf-8")
    (root / "config" / "avo.dependencies.json").write_text(
        json.dumps({"tools": {"avo-engine": _ENGINE_SPEC}}) + "\n",
        encoding="utf-8",
    )
    (root / "schemas" / "avo.project.schema.json").write_text("{}\n", encoding="utf-8")
    return root


class EnginePathsTests(unittest.TestCase):
    def test_clone_repo_root_is_pyproject_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_extract = Path(tmp) / "_internal"
            fake_extract.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"AVO_ROOT": ""}, clear=False):
                with mock.patch.object(sys, "frozen", False, create=True):
                    with mock.patch.object(
                        sys, "_MEIPASS", str(fake_extract), create=True
                    ):
                        root = repo_root()
            self.assertEqual(root, CHECKOUT)
            self.assertTrue((root / "pyproject.toml").is_file())
            self.assertNotEqual(root, fake_extract.resolve())

    def test_frozen_layout_finds_bundled_config_and_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meipass = _write_bundle(Path(tmp) / "_MEIPASS")
            with mock.patch.dict(os.environ, {"AVO_ROOT": ""}, clear=False):
                with mock.patch.object(sys, "frozen", True, create=True):
                    with mock.patch.object(sys, "_MEIPASS", str(meipass), create=True):
                        root = repo_root()
                        config = config_path("avo.config.json")
                        schema = schema_path("avo.project.schema.json")
            self.assertEqual(root, meipass.resolve())
            self.assertFalse((root / "pyproject.toml").is_file())
            self.assertFalse((root / ".git").exists())
            self.assertEqual(
                config.resolve(),
                (meipass / "config" / "avo.config.json").resolve(),
            )
            self.assertTrue(config.is_file())
            self.assertEqual(
                schema.resolve(),
                (meipass / "schemas" / "avo.project.schema.json").resolve(),
            )
            self.assertTrue(schema.is_file())

    def test_avo_root_override_wins_over_frozen_meipass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            meipass = _write_bundle(base / "_MEIPASS")
            override = _write_bundle(base / "user-root")
            (override / "config" / "avo.config.json").write_text(
                '{"source": "avo-root"}\n', encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"AVO_ROOT": str(override)}, clear=False):
                with mock.patch.object(sys, "frozen", True, create=True):
                    with mock.patch.object(sys, "_MEIPASS", str(meipass), create=True):
                        root = repo_root()
                        config = config_path("avo.config.json")
            self.assertEqual(root, override.resolve())
            self.assertEqual(
                config.resolve(),
                (override / "config" / "avo.config.json").resolve(),
            )
            self.assertIn("avo-root", config.read_text(encoding="utf-8"))

    def test_gate1_engine_mode_does_not_fail_on_missing_transcribe_py(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meipass = _write_bundle(Path(tmp) / "_MEIPASS")
            self.assertFalse((meipass / "pyproject.toml").is_file())
            self.assertFalse((meipass / "src" / "avo" / "transcribe.py").is_file())
            with mock.patch.dict(os.environ, {"AVO_ROOT": ""}, clear=False):
                with mock.patch.object(sys, "frozen", True, create=True):
                    with mock.patch.object(sys, "_MEIPASS", str(meipass), create=True):
                        results = run_checks(meipass, ci=False, optional=False)
            engine = next(r for r in results if r.tool == "avo-engine")
            self.assertNotEqual(
                engine.status,
                "FAIL",
                msg=(
                    f"engine mode must not FAIL on missing clone helpers: {engine.note}"
                ),
            )


if __name__ == "__main__":
    unittest.main()
