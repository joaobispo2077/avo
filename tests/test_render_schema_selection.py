from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import render


class RenderSchemaSelectionTests(unittest.TestCase):
    def test_v4_comparison_edl_uses_comparison_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            edl = Path(tmp) / "edl.json"
            edl.write_text(
                json.dumps(
                    {
                        "version": 4,
                        "caption_policy": {
                            "selectable_captions": True,
                            "visual_subtitles": False,
                            "language": "pt-BR",
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(render.schema_for_edl(edl), render.COMPARISON_SCHEMA)


if __name__ == "__main__":
    unittest.main()
