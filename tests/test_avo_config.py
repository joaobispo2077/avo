from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path_inserted = False


def _ensure_import_path() -> None:
    global sys_path_inserted
    if not sys_path_inserted:
        import sys

        sys.path.insert(0, str(ROOT))
        sys_path_inserted = True


class AvoConfigTests(unittest.TestCase):
    def test_avo_config_has_required_jobs(self) -> None:
        data = json.loads((ROOT / "config" / "avo.config.json").read_text(encoding="utf-8"))
        jobs = data["jobs"]
        for key in ("plan", "transcribe", "understand", "motion", "render", "cleanup"):
            self.assertIn(key, jobs, f"missing job {key}")

    def test_avo_dependencies_manifest_loads(self) -> None:
        data = json.loads((ROOT / "config" / "avo.dependencies.json").read_text(encoding="utf-8"))
        self.assertIn("tools", data)
        for required in ("speckit", "avo-engine", "watch-skill", "hyperframes"):
            self.assertIn(required, data["tools"])
            self.assertTrue(data["tools"][required].get("required"))


class ValidateDependenciesTests(unittest.TestCase):
    def test_gate1_passes_in_ci_mode(self) -> None:
        _ensure_import_path()
        from avo.validate_dependencies import main

        code = main(["--ci", "--root", str(ROOT)])
        self.assertEqual(code, 0)


class ValidateUsabilityTests(unittest.TestCase):
    def test_gate2_passes_in_ci_mode(self) -> None:
        _ensure_import_path()
        from avo.validate_usability import main

        code = main(["--ci", "--root", str(ROOT)])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
