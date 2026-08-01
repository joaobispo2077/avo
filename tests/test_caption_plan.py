from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import build_captions
import render


class CaptionPlanTests(unittest.TestCase):
    def test_terminal_periods_are_removed_but_questions_remain(self) -> None:
        text = "Primeira frase.\nFunciona mesmo?\nVersao 2.0."
        self.assertEqual(
            build_captions.strip_terminal_periods(text),
            "Primeira frase\nFunciona mesmo?\nVersao 2.0",
        )

    def test_burn_in_subset_clamps_at_sixty_seconds(self) -> None:
        source = (
            "1\n00:00:58,500 --> 00:01:01,500\nULTIMA FRASE.\n\n"
            "2\n00:01:02,000 --> 00:01:03,000\nFORA.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            full = root / "master.srt"
            burn = root / "caption-burn-in.srt"
            full.write_text(source, encoding="utf-8")
            count = build_captions.derive_burn_in_srt(full, burn, end_seconds=60)
            result = burn.read_text(encoding="utf-8")
            self.assertEqual(count, 1)
            self.assertIn("00:01:00,000", result)
            self.assertIn("ULTIMA FRASE", result)
            self.assertNotIn("FORA", result)
            self.assertNotIn("FRASE.", result)

    def test_seam_style_is_middle_center(self) -> None:
        self.assertIn("Alignment=5", render.SUB_FORCE_STYLE)
        self.assertNotIn("MarginV=90", render.SUB_FORCE_STYLE)

    def test_selectable_only_caption_generation_creates_no_burn_in_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript_dir = root / "transcripts"
            transcript_dir.mkdir()
            (transcript_dir / "main.json").write_text(
                '{"words":[{"type":"word","text":"Primeira","start":0.0,"end":0.4},'
                '{"type":"word","text":"frase.","start":0.4,"end":0.8}]}',
                encoding="utf-8",
            )
            edl = root / "edl.json"
            edl.write_text(
                '{"ranges":[{"source":"main","start":0,"end":1}],'
                '"caption_policy":{"selectable_captions":true,"visual_subtitles":false}}',
                encoding="utf-8",
            )
            output = root / "master.srt"
            count = build_captions.build_selectable_only(edl, output)
            self.assertEqual(count, 1)
            self.assertTrue(output.exists())
            self.assertFalse((root / "caption-burn-in.srt").exists())
            self.assertFalse((root / "caption-burn-in.ass").exists())


if __name__ == "__main__":
    unittest.main()

