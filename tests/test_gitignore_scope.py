from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GitignoreScopeTests(unittest.TestCase):
    def test_gitignore_has_provider_instance_rule(self) -> None:
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("providers/*/", text)
        self.assertIn("!providers/_template/", text)

    def test_bishop_provider_is_gitignored(self) -> None:
        path = "providers/bishop/avo.provider.json"
        r = subprocess.run(
            ["git", "check-ignore", "-v", path],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, msg=f"{path} should be ignored; stderr={r.stderr}")

    def test_template_provider_is_not_gitignored(self) -> None:
        path = "providers/_template/avo.provider.json"
        r = subprocess.run(
            ["git", "check-ignore", path],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(r.returncode, 0, msg=f"{path} must remain trackable")

    def test_example_project_has_no_personal_paths(self) -> None:
        data = json.loads((ROOT / "avo.project.example.json").read_text(encoding="utf-8"))
        blob = json.dumps(data)
        self.assertNotIn("bishop", blob.lower())
        self.assertNotIn("H:/", blob)
        self.assertNotIn("H:\\", blob)

    def test_validate_usability_does_not_require_bishop(self) -> None:
        src = (ROOT / "helpers" / "validate_usability.py").read_text(encoding="utf-8")
        self.assertNotIn("providers/bishop", src)


if __name__ == "__main__":
    unittest.main()
