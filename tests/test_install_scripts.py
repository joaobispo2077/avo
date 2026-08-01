from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallScriptTests(unittest.TestCase):
    def test_install_js_help_exits_zero(self) -> None:
        r = subprocess.run(
            ["node", "bin/install.cjs", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("AVO installer", r.stdout)

    def test_install_js_list_agents(self) -> None:
        r = subprocess.run(
            ["node", "bin/install.cjs", "--list"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("cursor", r.stdout)

    def test_install_js_dry_run_exits_zero(self) -> None:
        r = subprocess.run(
            ["node", "bin/install.cjs", "--dry-run", "--only", "cursor"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("dry-run", r.stdout.lower())

    def test_skills_json_exists(self) -> None:
        path = ROOT / "skills.json"
        self.assertTrue(path.is_file())

    def test_agent_skills_avo_exists(self) -> None:
        skill = ROOT / "agent-skills" / "avo" / "SKILL.md"
        self.assertTrue(skill.is_file())

    def test_skills_json_lists_all_avo_skills(self) -> None:
        import json

        data = json.loads((ROOT / "skills.json").read_text(encoding="utf-8"))
        names = {s["name"] for s in data.get("skills", [])}
        self.assertEqual(names, {"avo", "avo-pipeline", "avo-provider"})
        for entry in data["skills"]:
            self.assertTrue((ROOT / entry["path"]).is_file(), msg=entry["path"])

    def test_default_repo_slug(self) -> None:
        src = (ROOT / "bin" / "install.cjs").read_text(encoding="utf-8")
        self.assertIn("joaobispo2077/avo", src)
        self.assertNotIn("'browser-use/video-use'", src)

    def test_install_sh_default_repo(self) -> None:
        sh = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("joaobispo2077/avo", sh)

    def test_skills_json_repo_slug(self) -> None:
        import json

        data = json.loads((ROOT / "skills.json").read_text(encoding="utf-8"))
        self.assertEqual(data.get("repository"), "joaobispo2077/avo")


if __name__ == "__main__":
    unittest.main()
