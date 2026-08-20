"""task-014: dead-code gate runner + allowlist contract."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_checker():
    path = ROOT / "scripts/ci/check_deadcode.py"
    spec = importlib.util.spec_from_file_location("check_deadcode", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DeadcodeGateTests(unittest.TestCase):
    def test_allowlist_contract(self) -> None:
        raw = json.loads(
            (ROOT / "scripts/ci/deadcode-allowlist.json").read_text(encoding="utf-8")
        )
        self.assertEqual(raw["min_confidence"], 60)
        self.assertIsInstance(raw.get("items"), list)
        self.assertGreater(
            len(raw["items"]),
            0,
            msg="baseline allowlist must document dynamic/CLI false positives",
        )
        for entry in raw["items"]:
            self.assertTrue(str(entry["path"]).startswith("src/avo/"))
            self.assertTrue(entry["name"])
            self.assertTrue(str(entry["reason"]).strip())

    def test_check_deadcode_passes_on_current_tree(self) -> None:
        mod = _load_checker()
        self.assertEqual(mod.main(), 0)

    def test_missing_allowlist_entry_fails(self) -> None:
        mod = _load_checker()
        allowlist_path = ROOT / "scripts/ci/deadcode-allowlist.json"
        original = allowlist_path.read_text(encoding="utf-8")
        try:
            data = json.loads(original)
            self.assertGreaterEqual(len(data["items"]), 1)
            data["items"] = data["items"][1:]
            allowlist_path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(mod.main(), 1)
        finally:
            allowlist_path.write_text(original, encoding="utf-8")

    def test_stale_allowlist_entry_fails(self) -> None:
        mod = _load_checker()
        allowlist_path = ROOT / "scripts/ci/deadcode-allowlist.json"
        original = allowlist_path.read_text(encoding="utf-8")
        try:
            data = json.loads(original)
            data["items"] = list(data["items"]) + [
                {
                    "path": "src/avo/__init__.py",
                    "name": "__task014_phantom_unused__",
                    "reason": "synthetic stale entry for gate test",
                }
            ]
            allowlist_path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(mod.main(), 1)
        finally:
            allowlist_path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
