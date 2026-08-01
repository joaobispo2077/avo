from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "helpers"))

import render


class BlurayPs5RenderSchemaTests(unittest.TestCase):
    def test_feature_005_bluray_edl_uses_bluray_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            edl = Path(tmp) / "edl.json"
            edl.write_text(
                json.dumps(
                    {
                        "version": 5,
                        "feature_id": "005-bluray-ps5-gamevlog",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(render.schema_for_edl(edl), render.BLURAY_PS5_SCHEMA)


if __name__ == "__main__":
    unittest.main()
