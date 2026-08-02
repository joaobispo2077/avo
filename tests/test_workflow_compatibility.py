from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from avo import pack_transcripts
from avo import render


class WorkflowCompatibilityTests(unittest.TestCase):
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
