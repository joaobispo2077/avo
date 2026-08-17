from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from avo import pack_transcripts, render


class WorkflowCompatibilityTests(unittest.TestCase):
    def test_runtime_has_no_bespoke_splatoon_helpers(self) -> None:
        runtime_roots = (
            ROOT / "src" / "avo",
            ROOT / "commands" / "avo",
            ROOT / "agent-skills" / "avo-pipeline",
        )
        forbidden = (
            "splatoon",
            "sync-map-v017",
            "rebuild-v010",
            "audio-plus-128",
            "resync-calibration",
        )
        findings = []
        for base in runtime_roots:
            for path in base.rglob("*"):
                if path.is_file() and path.suffix in {".py", ".md", ".json"}:
                    lowered = path.read_text(encoding="utf-8", errors="ignore").lower()
                    if any(token in lowered for token in forbidden):
                        findings.append(str(path.relative_to(ROOT)))
        self.assertEqual([], findings)

    def test_every_command_uses_shared_timeline_gateway(self) -> None:
        commands = sorted((ROOT / "commands" / "avo").glob("*.md"))
        self.assertEqual(51, len(commands))
        for path in commands:
            text = path.read_text(encoding="utf-8")
            self.assertEqual(1, text.count("**Timeline integration:**"), path.name)
            self.assertEqual(1, text.count("## Shared timeline gateway"), path.name)
            mode = text.split("**Timeline integration:**", 1)[1].splitlines()[0].strip()
            self.assertIn(
                mode, {"Owns", "Evidence", "Consumes", "Profile", "Admin"}, path.name
            )

    def test_edl_is_only_a_generated_compatibility_projection(self) -> None:
        workflow = (ROOT / "docs" / "avo-workflow.md").read_text(encoding="utf-8")
        projection = (ROOT / "src" / "avo" / "timeline" / "projection.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "edit/edl.json is generated renderer compatibility output", workflow
        )
        self.assertIn(
            "canonical timeline → legacy EDL compatibility projection", projection
        )

    def test_local_transcript_packs_and_builds_srt(self) -> None:
        fixture = json.loads(
            (ROOT / "tests/fixtures/transcript_ptbr.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as tmp:
            edit = Path(tmp)
            transcripts = edit / "transcripts"
            transcripts.mkdir()
            transcript_path = transcripts / "clip.json"
            transcript_path.write_text(
                json.dumps(fixture, ensure_ascii=False), encoding="utf-8"
            )
            _, _, phrases = pack_transcripts.pack_one_file(transcript_path, 0.5)
            self.assertTrue(phrases)
            self.assertIn("Olá", phrases[0]["text"])

            edl = {
                "sources": {"clip": "/fixtures/clip-ptbr.mp4"},
                "ranges": [{"source": "clip", "start": 0.2, "end": 2.1}],
            }
            srt = edit / "master.srt"
            render.build_master_srt(edl, edit, srt)
            content = srt.read_text(encoding="utf-8")
            self.assertIn("OLÁ", content)
            self.assertIn("-->", content)


if __name__ == "__main__":
    unittest.main()
