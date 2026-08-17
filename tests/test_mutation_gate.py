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


if __name__ == "__main__":
    unittest.main()
