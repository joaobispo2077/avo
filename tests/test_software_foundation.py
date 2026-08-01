from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CURSOR_RULES = [
    "00-core-behavior.mdc",
    "10-branch-policy.mdc",
    "20-testing-and-tdd.mdc",
    "30-design-principles.mdc",
    "40-versioning-and-changelog.mdc",
    "50-documentation-policy.mdc",
]

GITHUB_INSTRUCTIONS = [
    "testing.instructions.md",
    "design-principles.instructions.md",
    "versioning-and-documentation.instructions.md",
]

CLAUDE_SKILLS = [
    "design-pattern-selection/SKILL.md",
    "architecture-selection/SKILL.md",
]


class SoftwareFoundationTests(unittest.TestCase):
    def test_changelog_exists_with_semver_note(self) -> None:
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("Semantic Versioning", text)
        self.assertIn("[Unreleased]", text)

    def test_foundation_docs_exist(self) -> None:
        for name in ("versioning.md", "branching.md", "software-foundation.md"):
            self.assertTrue((ROOT / "docs" / name).is_file(), msg=name)

    def test_cursor_foundation_rules_exist(self) -> None:
        rules_dir = ROOT / ".cursor" / "rules"
        for name in CURSOR_RULES:
            path = rules_dir / name
            self.assertTrue(path.is_file(), msg=name)
            text = path.read_text(encoding="utf-8")
            self.assertIn("alwaysApply: true", text)

    def test_github_copilot_foundation_instructions(self) -> None:
        copilot = (ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
        self.assertIn("Software foundation", copilot)
        for name in GITHUB_INSTRUCTIONS:
            self.assertTrue((ROOT / ".github" / "instructions" / name).is_file(), msg=name)

    def test_claude_foundation_skills_exist(self) -> None:
        base = ROOT / ".claude" / "skills"
        for rel in CLAUDE_SKILLS:
            self.assertTrue((base / rel).is_file(), msg=rel)

    def test_cursor_skills_mirrored(self) -> None:
        base = ROOT / ".cursor" / "skills"
        for rel in CLAUDE_SKILLS:
            self.assertTrue((base / rel).is_file(), msg=rel)

    def test_agents_md_has_foundation_section(self) -> None:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("## Software Engineering Foundation", text)
        self.assertIn("design-pattern-selection", text)
        self.assertIn("SemVer", text)


if __name__ == "__main__":
    unittest.main()
