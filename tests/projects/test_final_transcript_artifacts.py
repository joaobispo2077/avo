from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

sys.path.insert(0, str(SRC))

from avo import final_transcript_artifacts


class FinalTranscriptArtifactTests(unittest.TestCase):
    def test_writes_readable_artifacts_from_final_master_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = root / "20260721-switch-comparison-master-v001.json"
            transcript.write_text(
                json.dumps(
                    {
                        "text": "primeira frase. segunda frase",
                        "words": [
                            {"type": "word", "text": "primeira", "start": 0.0, "end": 0.4},
                            {"type": "word", "text": "frase.", "start": 0.4, "end": 0.8},
                            {"type": "word", "text": "segunda", "start": 1.2, "end": 1.7},
                            {"type": "word", "text": "frase", "start": 1.7, "end": 2.2},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            outputs = final_transcript_artifacts.write_artifacts(transcript)
            self.assertEqual(outputs["txt"].name, "20260721-switch-comparison-master-v001.txt")
            self.assertTrue(outputs["txt"].exists())
            self.assertTrue(outputs["md"].exists())
            self.assertTrue(outputs["srt"].exists())
            self.assertIn("primeira frase", outputs["txt"].read_text(encoding="utf-8"))
            self.assertIn("# 20260721-switch-comparison-master-v001", outputs["md"].read_text(encoding="utf-8"))
            self.assertIn("00:00:00,000 --> 00:00:00,800", outputs["srt"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
