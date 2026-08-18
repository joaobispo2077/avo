"""ci-quality-hardening: sticky PR report markdown (no GitHub API)."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class QualityPrReportTests(unittest.TestCase):
    def test_quality_table_marks_skipped_after_fail(self) -> None:
        mod = _load("write_quality_pr_report", "scripts/ci/write_quality_pr_report.py")
        text = mod.build_markdown(
            {
                "lint": "success",
                "format": "failure",
                "coverage": "skipped",
            },
            coverage_json=Path("missing.json"),
            floor=68.0,
        )
        self.assertIn("## Software quality", text)
        self.assertIn("| Lint | **PASS** |", text)
        self.assertIn("| Format | **FAIL** |", text)
        self.assertIn("| Coverage | **SKIPPED** |", text)
        self.assertIn("floor 68%", text)

    def test_quality_coverage_detail_from_json(self) -> None:
        mod = _load("write_quality_pr_report", "scripts/ci/write_quality_pr_report.py")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            path.write_text(
                json.dumps(
                    {
                        "totals": {
                            "percent_covered": 71.25,
                            "covered_lines": 712,
                            "num_statements": 1000,
                        }
                    }
                ),
                encoding="utf-8",
            )
            detail = mod.coverage_detail(path, 68.0)
        self.assertIn("71.25%", detail)
        self.assertIn("712/1000 lines", detail)

    def test_mutation_report_matches_maxframe_shape(self) -> None:
        mod = _load(
            "write_mutation_pr_report", "scripts/ci/write_mutation_pr_report.py"
        )
        text = mod.build_markdown(
            profile="light",
            floor=40.0,
            stats={"killed": 8, "survived": 2, "timeout": 1, "total": 11},
            timeout_minutes=20,
        )
        self.assertIn("## Mutation tests", text)
        self.assertIn("- **Profile:** light", text)
        self.assertIn("80.00%", text)
        self.assertIn("Passing (>= 40)", text)
        self.assertIn("| Killed | 8 |", text)
        self.assertIn("| Survived | 2 |", text)
        self.assertIn("| Timeout | 1 |", text)

    def test_mutation_report_without_stats(self) -> None:
        mod = _load(
            "write_mutation_pr_report", "scripts/ci/write_mutation_pr_report.py"
        )
        text = mod.build_markdown(
            profile="light",
            floor=40.0,
            stats=None,
            timeout_minutes=20,
        )
        self.assertIn("stats JSON was not found", text)
        self.assertIn("20 minutes", text)


if __name__ == "__main__":
    unittest.main()
