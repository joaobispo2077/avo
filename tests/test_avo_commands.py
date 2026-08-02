"""Command file parity tests for /avo.* slash commands."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "commands" / "avo"
REFS = ROOT / "agent-skills" / "avo-pipeline" / "references"
DOCS_PIPELINE = ROOT / "docs" / "avo-pipeline"

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
    "deliver.md",
    "shorts.md",
    "reframe.md",
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
        self.assertIn("/avo.deliver", text)
        self.assertIn("/avo.shorts", text)
        self.assertIn("/avo.reframe", text)


if __name__ == "__main__":
    unittest.main()
