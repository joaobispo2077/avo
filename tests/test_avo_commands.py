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
LOCALE_STUB = ROOT / "specs" / "backlog" / "locale-stub.md"

WAVE3_COMMANDS = {
    "launch.md",
    "music-video.md",
    "talking-head.md",
    "figma.md",
    "end-screen.md",
    "color.md",
    "sync.md",
    "media.md",
}

WAVE4_COMMANDS = {
    "motion-graphics.md",
    "general.md",
    "remotion-port.md",
    "screencast.md",
    "format.md",
    "framework.md",
    "grade.md",
}

WAVE5_COMMANDS = {
    "issues.md",
    "supporters.md",
    "creators.md",
}

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
    "chapters.md",
    "thumbnail.md",
    "deliver.md",
    "shorts.md",
    "reframe.md",
    "podcast-clip.md",
    "trailer.md",
    "pr-video.md",
    "changelog-video.md",
    "explainer.md",
    "slideshow.md",
    "retention.md",
    "animation-qc.md",
    "telemetry.md",
    "learndown.md",
    "cleanup.md",
    "stats.md",
} | WAVE3_COMMANDS | WAVE4_COMMANDS | WAVE5_COMMANDS

EXPECTED_UTILITY_REFS = {
    "help.md",
    "guidelines.md",
    "guidelines-youtube.md",
    "guidelines-eq.md",
    "guidelines-tiktok.md",
    "guidelines-shorts.md",
    "guidelines-podcast.md",
    "docs.md",
    "transcribe.md",
    "telemetry.md",
    "learndown.md",
    "cleanup.md",
    "stats.md",
    "captions.md",
    "rights.md",
    "audio-qc.md",
    "chapters.md",
    "thumbnail.md",
    "deliver.md",
    "shorts.md",
    "reframe.md",
    "podcast-clip.md",
    "trailer.md",
    "pr-video.md",
    "changelog-video.md",
    "explainer.md",
    "slideshow.md",
    "retention.md",
    "animation-qc.md",
    "launch.md",
    "music-video.md",
    "talking-head.md",
    "figma.md",
    "end-screen.md",
    "color.md",
    "sync.md",
    "media.md",
    "motion-graphics.md",
    "general.md",
    "remotion-port.md",
    "screencast.md",
    "format.md",
    "framework.md",
    "grade.md",
    "issues.md",
    "supporters.md",
    "creators.md",
}

EXPECTED_REVIEW_TEMPLATES = {
    "approval-gate-manifest.md",
    "rights-audit.md",
    "audio-qc.md",
    "end-screen-checklist.md",
    "color-qc.md",
    "sync-check.md",
    "format-diagnosis.md",
    "framework-selection.md",
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

    def test_command_map_lists_wave2_commands(self) -> None:
        text = (REFS / "command-map.md").read_text(encoding="utf-8")
        for cmd in (
            "/avo.help",
            "/avo.captions",
            "/avo.rights",
            "/avo.audio-qc",
            "/avo.chapters",
            "/avo.thumbnail",
            "/avo.deliver",
            "/avo.shorts",
            "/avo.reframe",
            "/avo.podcast-clip",
            "/avo.trailer",
            "/avo.pr-video",
            "/avo.changelog-video",
            "/avo.explainer",
            "/avo.slideshow",
            "/avo.retention",
            "/avo.animation-qc",
        ):
            self.assertIn(cmd, text, cmd)

    def test_command_map_lists_wave3_commands(self) -> None:
        text = (REFS / "command-map.md").read_text(encoding="utf-8")
        for cmd in (
            "/avo.launch",
            "/avo.music-video",
            "/avo.talking-head",
            "/avo.figma",
            "/avo.end-screen",
            "/avo.color",
            "/avo.sync",
            "/avo.media",
        ):
            self.assertIn(cmd, text, cmd)

    def test_command_map_lists_wave4_commands(self) -> None:
        text = (REFS / "command-map.md").read_text(encoding="utf-8")
        for cmd in (
            "/avo.motion-graphics",
            "/avo.general",
            "/avo.remotion-port",
            "/avo.screencast",
            "/avo.format",
            "/avo.framework",
            "/avo.grade",
        ):
            self.assertIn(cmd, text, cmd)

    def test_command_map_lists_wave5_commands(self) -> None:
        text = (REFS / "command-map.md").read_text(encoding="utf-8")
        for cmd in (
            "/avo.issues",
            "/avo.supporters",
            "/avo.creators",
        ):
            self.assertIn(cmd, text, cmd)

    def test_help_wave5_discovery(self) -> None:
        text = (REFS / "help.md").read_text(encoding="utf-8")
        self.assertIn("/avo.issues", text)
        self.assertIn("/avo.supporters", text)
        self.assertIn("/avo.creators", text)

    def test_issue_templates_exist(self) -> None:
        template_dir = ROOT / ".github" / "ISSUE_TEMPLATE"
        for name in (
            "config.yml",
            "bug_report.yml",
            "documentation.yml",
            "enhancement.yml",
            "third_party_resources.yml",
            "other_request.yml",
        ):
            self.assertTrue((template_dir / name).is_file(), name)

    def test_creators_doc_exists(self) -> None:
        self.assertTrue((ROOT / "docs" / "creators.md").is_file())

    def test_help_wave4_sections(self) -> None:
        text = (REFS / "help.md").read_text(encoding="utf-8")
        self.assertIn("### Motion & composition", text)
        self.assertIn("/avo.format", text)
        self.assertIn("/avo.framework", text)
        self.assertIn("/avo.motion-graphics", text)
        self.assertIn("/avo.general", text)
        self.assertIn("/avo.grade", text)

    def test_help_wave3_sections(self) -> None:
        text = (REFS / "help.md").read_text(encoding="utf-8")
        self.assertIn("/avo.talking-head", text)
        self.assertIn("/avo.end-screen", text)
        self.assertIn("/avo.color", text)
        self.assertIn("/avo.sync", text)
        self.assertIn("/avo.launch", text)
        self.assertIn("/avo.media", text)

    def test_help_grouped_sections(self) -> None:
        text = (REFS / "help.md").read_text(encoding="utf-8")
        self.assertIn("### QC & deliver", text)
        self.assertIn("### Format orchestrators", text)
        self.assertIn("### Upload prep", text)
        self.assertIn("### Content", text)
        self.assertIn("/avo.rights", text)
        self.assertIn("/avo.podcast-clip", text)
        self.assertIn("/avo.chapters", text)
        self.assertIn("/avo.pr-video", text)

    def test_deliver_cross_links_rights_and_audio_qc(self) -> None:
        text = (REFS / "deliver.md").read_text(encoding="utf-8")
        self.assertIn("rights-audit", text)
        self.assertIn("audio-qc", text)

    def test_review_templates_exist(self) -> None:
        found = {p.name for p in REVIEW_TEMPLATES.glob("*.md")}
        self.assertTrue(EXPECTED_REVIEW_TEMPLATES.issubset(found), found - EXPECTED_REVIEW_TEMPLATES)

    def test_skills_json_still_three_entries(self) -> None:
        import json

        data = json.loads(SKILLS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(len(data["skills"]), 3)

    def test_locale_stub_stop_gate(self) -> None:
        self.assertTrue(LOCALE_STUB.is_file())
        text = LOCALE_STUB.read_text(encoding="utf-8")
        self.assertIn("do not implement", text)
        self.assertFalse((ROOT / "agent-skills" / "avo-locale").exists())


if __name__ == "__main__":
    unittest.main()
