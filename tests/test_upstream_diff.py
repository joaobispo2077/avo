from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UpstreamDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT))

    def test_diff_generates_latest_and_summary(self) -> None:
        import tempfile
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "diff_engine_helpers",
            ROOT / "scripts/upstream/diff-engine-helpers.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bundled = tmp_path / "bundled"
            upstream = tmp_path / "upstream"
            bundled.mkdir()
            upstream.mkdir()
            (bundled / "shared.py").write_text("avo = 1\n", encoding="utf-8")
            (upstream / "shared.py").write_text("upstream = 1\n", encoding="utf-8")
            (bundled / "avo_only.py").write_text("# avo\n", encoding="utf-8")
            out = tmp_path / "diffs"

            code = mod.main(
                [
                    "--root",
                    str(tmp_path),
                    "--bundled",
                    str(bundled),
                    "--upstream",
                    str(upstream),
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            latest = json.loads((out / "LATEST.json").read_text(encoding="utf-8"))
            self.assertIn("summaryPath", latest)
            summary_path = tmp_path / latest["summaryPath"]
            diff_dir = tmp_path / latest["diffDir"]
            self.assertTrue(summary_path.is_file())
            manifest = json.loads((diff_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["changedCount"], 1)
            self.assertEqual(manifest["onlyInAvoCount"], 1)


if __name__ == "__main__":
    unittest.main()
