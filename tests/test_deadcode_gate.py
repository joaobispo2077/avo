"""task-014: dead-code gate runner + allowlist contract."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load_checker():
    path = ROOT / "scripts/ci/check_deadcode.py"
    spec = importlib.util.spec_from_file_location("check_deadcode", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DeadcodeGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def _checker(self):
        mod = _load_checker()
        directory = Path(self.temporary.name)
        mod.REPORT_PATH = directory / "deadcode.json"
        mod.ALLOWLIST_PATH = directory / "allowlist.json"
        mod.ALLOWLIST_PATH.write_text(
            (ROOT / "scripts/ci/deadcode-allowlist.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return mod

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
        mod = self._checker()
        self.assertEqual(mod.main(), 0)

    def test_missing_allowlist_entry_fails(self) -> None:
        mod = self._checker()
        allowlist_path = mod.ALLOWLIST_PATH
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
        mod = self._checker()
        allowlist_path = mod.ALLOWLIST_PATH
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

    def test_report_records_only_actual_matched_exceptions(self) -> None:
        mod = self._checker()
        entry = {
            "path": "src/avo/sample.py",
            "name": "allowed",
            "reason": "CLI adapter",
        }
        stale = {**entry, "name": "gone"}
        findings = [
            (entry["path"], "allowed", "function", 4, 60, "unused function 'allowed'"),
            (
                entry["path"],
                "unexpected",
                "variable",
                8,
                100,
                "unused variable 'unexpected'",
            ),
        ]
        with (
            mock.patch.object(
                mod,
                "_load_allowlist",
                return_value=(
                    60,
                    {
                        (entry["path"], entry["name"]): entry,
                        (stale["path"], stale["name"]): stale,
                    },
                ),
            ),
            mock.patch.object(mod, "_collect_findings", return_value=findings),
            mock.patch.dict(
                mod.os.environ,
                {"AVO_QUALITY_SHA": "b" * 40, "AVO_QUALITY_RUN_ID": "88"},
            ),
        ):
            self.assertEqual(mod.main(), 1)
        report = json.loads(mod.REPORT_PATH.read_text())
        self.assertEqual(
            report["counts"],
            {"findings": 2, "allowlisted": 1, "unwaived": 1, "stale": 1, "errors": 0},
        )
        self.assertEqual(report["policy"]["configured_allowlist_entries"], 2)
        self.assertEqual(report["allowlisted"][0]["reason"], "CLI adapter")
        self.assertEqual(report["violations"][0]["confidence"], 100)
        self.assertEqual(report["sha"], "b" * 40)
        self.assertEqual(report["run_id"], "88")
        self.assertTrue(report["complete"])

    def test_failed_scan_has_unknown_counts(self) -> None:
        mod = self._checker()
        with mock.patch.object(
            mod, "_collect_findings", side_effect=ValueError("invalid source")
        ):
            self.assertEqual(mod.main(), 1)
        report = json.loads(mod.REPORT_PATH.read_text())
        self.assertIsNone(report["counts"])
        self.assertEqual(report["status"], "ERROR")
        self.assertFalse(report["complete"])

    def test_vulture_parse_error_cannot_return_empty_success(self) -> None:
        mod = self._checker()
        broken = mock.Mock(exit_code=1)
        with (
            mock.patch.object(mod, "Vulture", return_value=broken),
            self.assertRaisesRegex(ValueError, "could not analyze"),
        ):
            mod._collect_findings(60)


if __name__ == "__main__":
    unittest.main()
