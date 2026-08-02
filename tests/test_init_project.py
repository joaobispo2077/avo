from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

from avo import init_project  # noqa: E402


class InitProjectTests(unittest.TestCase):
    def test_print_only_with_template_provider(self) -> None:
        code = init_project.main(
            [
                "--provider",
                "_template",
                "--raw-dir",
                "/tmp/avo-test-raw",
                "--print",
                "--yes",
            ]
        )
        self.assertEqual(code, 0)

    def test_build_project_structure(self) -> None:
        manifest = init_project.load_provider("_template", root=ROOT)
        project = init_project.build_project(
            "_template",
            "H:/footage/demo",
            provider_manifest=manifest,
            config=init_project.load_config(ROOT),
        )
        self.assertEqual(project["provider"], "_template")
        self.assertEqual(project["rawDir"], "H:/footage/demo")
        self.assertIn("assets", project)

    def test_help_exits_zero(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "avo.init_project", "--help"],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("avo.project.json", proc.stdout)


if __name__ == "__main__":
    unittest.main()
