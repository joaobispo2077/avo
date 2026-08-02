"""Command file parity tests for /avo.* slash commands."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "commands" / "avo"
REFS = ROOT / "agent-skills" / "avo-pipeline" / "references"
DOCS_PIPELINE = ROOT / "docs" / "avo-pipeline"
REVIEW_TEMPLATES = ROOT / "docs" / "templates" / "review"
SKILLS_JSON = ROOT / "skills.json"

EXPECTED_COMMANDS = {
    "help.md",
    "guidelines.md",
    "docs.md",
    "pipeline.md",
    "trim.md",
    "transcribe.md",
    "sound.md",
    "audit.md",
    "watch.md",
    "motion.md",
    "captions.md",
    "rights.md",
    "audio-qc.md",
    "deliver.md",
    "shorts.md",
    "reframe.md",
    "telemetry.md",
    "learndown.md",
    "cleanup.md",
    "stats.md",
}

EXPECTED_UTILITY_REFS = {
    "help.md",
    "guidelines.md",
    "guidelines-youtube.md",
    "guidelines-eq.md",
    "guidelines-tiktok.md",
    "guidelines-shorts.md",
    "docs.md",
    "transcribe.md",
    "telemetry.md",
    "learndown.md",
    "cleanup.md",
    "stats.md",
    "captions.md",
    "rights.md",
    "audio-qc.md",
    "deliver.md",
    "shorts.md",
    "reframe.md",
}

EXPECTED_REVIEW_TEMPLATES = {
    "approval-gate-manifest.md",
    "rights-audit.md",
    "audio-qc.md",
}


class AvoCommandParityTests(unittest.TestCase):
    def test_all_command_files_exist(self) -> None:
        found = {p.name for p in COMMANDS.glob("*.md")}
        self.assertTrue(EXPECTED_COMMANDS.issubset(found), found - EXPECTED_COMMANDS)

    def test_utility_references_exist(self) -> None:
        for name in EXPECTED_UTILITY_REFS:
            self.assertTrue((REFS / name).is_file(), name)

    def test_docs_avo_pipeline_removed(self) -> None:
        self.assertFalse(DOCS_PIPELINE.exists(), "docs/avo-pipeline/ must be removed")

    def test_command_map_lists_help(self) -> None:
        text = (REFS / "command-map.md").read_text(encoding="utf-8")
        self.assertIn("/avo.help", text)
        self.assertIn("/avo.guidelines", text)
        self.assertIn("/avo.transcribe", text)
        self.assertIn("/avo.captions", text)
        self.assertIn("/avo.rights", text)
        self.assertIn("/avo.audio-qc", text)
        self.assertIn("/avo.deliver", text)
        self.assertIn("/avo.shorts", text)
        self.assertIn("/avo.reframe", text)

    def test_help_qc_and_deliver_section(self) -> None:
        text = (REFS / "help.md").read_text(encoding="utf-8")
        self.assertIn("### QC & deliver", text)
        self.assertIn("/avo.rights", text)
        self.assertIn("/avo.audio-qc", text)
        self.assertIn("/avo.audit", text)
        self.assertIn("/avo.deliver", text)

    def test_review_templates_exist(self) -> None:
        found = {p.name for p in REVIEW_TEMPLATES.glob("*.md")}
        self.assertTrue(EXPECTED_REVIEW_TEMPLATES.issubset(found), found - EXPECTED_REVIEW_TEMPLATES)

    def test_skills_json_still_three_entries(self) -> None:
        import json

        data = json.loads(SKILLS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(len(data["skills"]), 3)


if __name__ == "__main__":
    unittest.main()
