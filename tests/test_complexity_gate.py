"""task-010: complexity gate runner + allowlist contract."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load_checker():
    path = ROOT / "scripts/ci/check_complexity.py"
    spec = importlib.util.spec_from_file_location("check_complexity", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ComplexityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def _checker(self):
        mod = _load_checker()
        directory = Path(self.temporary.name)
        mod.REPORT_PATH = directory / "complexity.json"
        mod.ALLOWLIST_PATH = directory / "allowlist.json"
        mod.ALLOWLIST_PATH.write_text(
            (ROOT / "scripts/ci/complexity-allowlist.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return mod

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
        mod = self._checker()
        self.assertEqual(mod.main(), 0)

    def test_missing_allowlist_entry_fails(self) -> None:
        mod = self._checker()
        allowlist_path = mod.ALLOWLIST_PATH
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

    def test_report_counts_measured_locations_and_matched_exceptions(self) -> None:
        mod = self._checker()
        entry = {
            "path": "src/avo/sample.py",
            "name": "allowed",
            "complexity": 11,
            "reason": "dynamic boundary",
        }
        stale = {**entry, "name": "gone"}
        blocks = [
            {"name": "allowed", "complexity": 12, "lineno": 4},
            {"name": "unexpected", "complexity": 11, "lineno": 8},
            {"name": "small", "complexity": 2, "lineno": 12},
        ]
        with (
            mock.patch.object(
                mod,
                "_load_allowlist",
                return_value={
                    (entry["path"], entry["name"]): entry,
                    (stale["path"], stale["name"]): stale,
                },
            ),
            mock.patch.object(
                mod, "analyze", return_value=(0, {"src/avo/sample.py": blocks})
            ),
            mock.patch.dict(
                mod.os.environ,
                {"AVO_QUALITY_SHA": "a" * 40, "AVO_QUALITY_RUN_ID": "99"},
            ),
        ):
            self.assertEqual(mod.main(), 1)
        report = json.loads(mod.REPORT_PATH.read_text())
        self.assertEqual(
            report["counts"],
            {
                "measured_blocks": 3,
                "above_threshold": 2,
                "allowlisted": 1,
                "unwaived": 1,
                "worsened": 1,
                "stale": 1,
                "errors": 0,
            },
        )
        self.assertEqual(report["policy"]["configured_allowlist_entries"], 2)
        self.assertEqual(report["allowlisted"][0]["reason"], "dynamic boundary")
        self.assertEqual(report["violations"][0]["line"], 8)
        self.assertEqual(report["sha"], "a" * 40)
        self.assertEqual(report["run_id"], "99")
        self.assertTrue(report["complete"])
        self.assertEqual(report["status"], "FAIL")

    def test_parse_failure_is_explicit_incomplete_measurement(self) -> None:
        mod = self._checker()
        with (
            mock.patch.object(mod, "_load_allowlist", return_value={}),
            mock.patch.object(
                mod,
                "analyze",
                return_value=(0, {"src/avo/broken.py": {"error": "invalid syntax"}}),
            ),
        ):
            self.assertEqual(mod.main(), 1)
        report = json.loads(mod.REPORT_PATH.read_text())
        self.assertFalse(report["complete"])
        self.assertEqual(report["status"], "ERROR")
        self.assertEqual(report["errors"][0]["path"], "src/avo/broken.py")

    def test_execution_failure_replaces_old_measurement_with_unknown_counts(
        self,
    ) -> None:
        mod = self._checker()
        mod.REPORT_PATH.write_text('{"counts":{"unwaived":0},"status":"PASS"}')
        with mock.patch.object(
            mod, "analyze", side_effect=OSError("analyzer unavailable")
        ):
            self.assertEqual(mod.main(), 1)
        report = json.loads(mod.REPORT_PATH.read_text())
        self.assertIsNone(report["counts"])
        self.assertFalse(report["complete"])
        self.assertIn("analyzer unavailable", report["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
