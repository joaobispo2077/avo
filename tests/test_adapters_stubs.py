from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AdapterStubTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT))
        from avo.adapters.base import JobRequest

        self.request = JobRequest(job="plan", label="local", argv=[], root=ROOT)

    def test_speckit_stub_when_marker_present(self) -> None:
        from avo.adapters.stubs.plan_speckit import SpeckitStubAdapter

        if not (ROOT / ".specify").exists():
            self.skipTest(".specify marker missing")
        result = SpeckitStubAdapter().run(self.request)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("stub", result.stderr)

    def test_registry_has_stub_jobs(self) -> None:
        from avo.adapters.registry import JOB_REGISTRIES

        for job in ("understand", "motion", "memory", "plan"):
            self.assertIn(job, JOB_REGISTRIES)


if __name__ == "__main__":
    unittest.main()
