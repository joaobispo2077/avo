"""task-019: mutation score floor evaluator (no live mutmut run)."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts/ci/check_mutation.py"
    spec = importlib.util.spec_from_file_location("check_mutation", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MutationGateTests(unittest.TestCase):
    def test_config_has_light_and_full_floors(self) -> None:
        raw = json.loads(
            (ROOT / "scripts/ci/mutation-config.json").read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(float(raw["light"]["min_killed_percent"]), 40)
        self.assertGreaterEqual(float(raw["full"]["min_killed_percent"]), 50)

    def test_evaluate_fails_below_floor(self) -> None:
        mod = _load()
        ok, msg = mod.evaluate(
            {"killed": 1, "survived": 9, "total": 10},
            min_killed_percent=40.0,
        )
        self.assertFalse(ok)
        self.assertIn("10.0%", msg)

    def test_evaluate_passes_at_floor(self) -> None:
        mod = _load()
        ok, _msg = mod.evaluate(
            {"killed": 4, "survived": 6, "total": 10},
            min_killed_percent=40.0,
        )
        self.assertTrue(ok)

    def test_zero_mutants_fail(self) -> None:
        mod = _load()
        ok, _msg = mod.evaluate(
            {"killed": 0, "survived": 0, "total": 0},
            min_killed_percent=40.0,
        )
        self.assertFalse(ok)

    def test_unresolved_mutants_never_pass_or_publish_efficacy(self) -> None:
        mod = _load()
        for state in (
            "timeout",
            "suspicious",
            "not_checked",
            "check_was_interrupted_by_user",
            "check_was_interrupted",
            "no_tests",
            "untested",
            "skipped",
            "segfault",
            "caught_by_type_check",
        ):
            with self.subTest(state=state):
                stats = {"killed": 8, "survived": 2, state: 90, "total": 100}
                ok, message = mod.evaluate(stats, min_killed_percent=40)
                self.assertFalse(ok)
                self.assertIn("incomplete", message)
                result = mod.mutation_evaluation(stats, min_killed_percent=40)
                self.assertEqual(result["status"], "INCOMPLETE")
                self.assertFalse(result["complete"])
                self.assertIsNone(result["score"])
                self.assertEqual(result["unresolved"], 90)

    def test_counts_are_genuine_nonnegative_integers_and_account_for_total(self):
        mod = _load()
        for invalid in (True, False, -1, 1.5, "8", None):
            for key in ("killed", "survived", "total", "timeout"):
                with self.subTest(key=key, invalid=invalid):
                    stats = {"killed": 8, "survived": 2, "total": 10, key: invalid}
                    result = mod.mutation_evaluation(stats, min_killed_percent=40)
                    self.assertEqual(result["status"], "INVALID")
                    self.assertFalse(result["complete"])
                    self.assertIsNone(result["score"])
        excessive = mod.mutation_evaluation(
            {"killed": 8, "survived": 2, "total": 1}, min_killed_percent=40
        )
        self.assertEqual(excessive["status"], "INVALID")
        missing = mod.mutation_evaluation(
            {"killed": 8, "survived": 2, "total": 11}, min_killed_percent=40
        )
        self.assertEqual(missing["status"], "INCOMPLETE")
        self.assertEqual(missing["unresolved"], 1)
        self.assertIn("unaccounted", missing["reason"])
        self.assertIsNone(missing["score"])

    def test_missing_required_counts_and_conflicting_aliases_fail(self):
        mod = _load()
        for missing in ("killed", "survived", "total"):
            stats = {"killed": 8, "survived": 2, "total": 10}
            del stats[missing]
            result = mod.mutation_evaluation(stats, min_killed_percent=40)
            self.assertEqual(result["status"], "INVALID")
        result = mod.mutation_evaluation(
            {"killed": 8, "survived": 2, "total": 11, "timeout": 1, "timeouts": 2},
            min_killed_percent=40,
        )
        self.assertEqual(result["status"], "INVALID")

    def test_completed_evaluation_preserves_existing_floor(self):
        mod = _load()
        result = mod.mutation_evaluation(
            {"killed": 4, "survived": 6, "total": 10}, min_killed_percent=40
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["complete"])
        self.assertEqual(result["score"], 40.0)
        self.assertEqual(result["unresolved"], 0)
        self.assertEqual(result["counts"]["total"], 10)

    def test_profiles_exclude_cli_tools_and_mcp_directory(self) -> None:
        raw = json.loads(
            (ROOT / "scripts/ci/mutation-config.json").read_text(encoding="utf-8")
        )
        for name in ("light", "full"):
            paths = raw[name]["source_paths"]
            self.assertNotIn("src/avo/mcp", paths)
            self.assertTrue(all("cli_tools.py" not in p for p in paths))
            self.assertGreaterEqual(int(raw[name]["job_timeout_minutes"]), 20)
            self.assertNotIn(
                "tests/test_avo_config.py",
                raw[name]["pytest_add_cli_args_test_selection"],
            )
            self.assertNotIn(
                "tests/test_gitignore_scope.py",
                raw[name]["pytest_add_cli_args_test_selection"],
            )

    def test_runners_export_cicd_stats_before_floor_check(self) -> None:
        for rel in (
            "scripts/ci/run-mutation-light.sh",
            "scripts/ci/quality-mutation.sh",
        ):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("mutmut export-cicd-stats", text)
            self.assertLess(
                text.index("mutmut export-cicd-stats"),
                text.index("check_mutation.py"),
            )

    def test_light_runner_stamps_only_after_export(self) -> None:
        text = (ROOT / "scripts/ci/run-mutation-light.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", text)
        export_at = text.index("mutmut export-cicd-stats")
        stamp_at = text.index("--stamp")
        check_at = text.index("check_mutation.py")
        self.assertLess(text.index("mutmut run"), export_at)
        self.assertLess(export_at, stamp_at)
        self.assertLess(stamp_at, check_at)

    def test_patch_mutmut_profile_round_trip(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "patch_mutmut_profile",
            ROOT / "scripts/ci/patch_mutmut_profile.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        original = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        try:
            mod.apply_profile("light")
            patched = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn("src/avo/mcp/bridge.py", patched)
            self.assertNotIn(
                "src/avo/validate_edl.py",
                patched.split("[tool.mutmut]", 1)[1].split("also_copy", 1)[0],
            )
            self.assertIn("tests/test_mcp_bridge.py", patched)
        finally:
            mod.restore()
        restored = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(original, restored)


if __name__ == "__main__":
    unittest.main()
