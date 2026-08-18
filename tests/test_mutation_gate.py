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

    def test_profiles_exclude_cli_tools_and_mcp_directory(self) -> None:
        raw = json.loads(
            (ROOT / "scripts/ci/mutation-config.json").read_text(encoding="utf-8")
        )
        for name in ("light", "full"):
            paths = raw[name]["source_paths"]
            self.assertNotIn("src/avo/mcp", paths)
            self.assertTrue(all("cli_tools.py" not in p for p in paths))
            self.assertGreaterEqual(int(raw[name]["job_timeout_minutes"]), 20)

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
