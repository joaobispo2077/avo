"""task-010: complexity gate runner + allowlist contract."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_checker():
    path = ROOT / "scripts/ci/check_complexity.py"
    spec = importlib.util.spec_from_file_location("check_complexity", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ComplexityGateTests(unittest.TestCase):
    def test_allowlist_entries_have_reasons_and_ceilings(self) -> None:
        raw = json.loads(
            (ROOT / "scripts/ci/complexity-allowlist.json").read_text(encoding="utf-8")
        )
        self.assertEqual(raw["max_absolute"], "B")
        self.assertGreaterEqual(len(raw["blocks"]), 1)
        for entry in raw["blocks"]:
            self.assertTrue(str(entry["path"]).startswith("src/avo/"))
            self.assertTrue(entry["name"])
            self.assertGreaterEqual(int(entry["complexity"]), 11)
            self.assertIn(entry["rank"], {"C", "D", "E", "F"})
            self.assertTrue(entry["reason"].strip())

    def test_check_complexity_passes_on_current_tree(self) -> None:
        mod = _load_checker()
        self.assertEqual(mod.main(), 0)

    def test_missing_allowlist_entry_fails(self) -> None:
        mod = _load_checker()
        allowlist_path = ROOT / "scripts/ci/complexity-allowlist.json"
        original = allowlist_path.read_text(encoding="utf-8")
        try:
            data = json.loads(original)
            # Drop the highest-complexity entry so the gate must fail.
            data["blocks"] = sorted(
                data["blocks"], key=lambda b: int(b["complexity"]), reverse=True
            )[1:]
            allowlist_path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(mod.main(), 1)
        finally:
            allowlist_path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
