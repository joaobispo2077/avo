"""ci-quality-hardening: sticky PR report markdown (no GitHub API)."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertIn("## Software metrics", text)
        self.assertNotIn("## Software quality\n", text)
        self.assertIn("| Lint | **PASS** |", text)
        self.assertIn("| Format | **FAIL** |", text)
        self.assertIn("| Coverage | **SKIPPED** |", text)
        self.assertIn("| Gate | Status | Metric | What this checks |", text)
        self.assertIn("Ruff", text)
        self.assertIn("68%", text)
        self.assertIn("**Overall: FAIL**", text)
        self.assertNotIn("**Overall: PASS**", text)

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

    def test_mutation_metrics_document_uses_counts_only(self) -> None:
        mod = _load(
            "write_mutation_pr_report", "scripts/ci/write_mutation_pr_report.py"
        )
        sha = "a" * 40
        self.assertIsNone(
            mod.mutation_metrics_document(
                {"score": 99.0},
                sha=sha,
                floor=40.0,
            )
        )
        self.assertIsNone(
            mod.mutation_metrics_document(
                {"killed": 8, "survived": 2},
                sha="",
                floor=40.0,
            )
        )
        doc = mod.mutation_metrics_document(
            {"killed": 8, "survived": 2, "score": 1},
            sha=sha,
            floor=40.0,
        )
        self.assertEqual(
            doc,
            {"sha": sha, "killed": 8, "survived": 2, "floor": 40.0},
        )
        self.assertNotIn("score", doc)

    def test_restored_cache_is_not_passing_when_clean_tests_failed(self) -> None:
        """PR 82: cache restored 207/112 after clean tests never started mutmut."""
        mod = _load(
            "write_mutation_pr_report", "scripts/ci/write_mutation_pr_report.py"
        )
        current = "b" * 40
        cached_cases = [
            {"killed": 207, "survived": 112, "timeout": 0, "total": 319},
            {
                "killed": 207,
                "survived": 112,
                "timeout": 0,
                "total": 319,
                "sha": "a" * 40,
                "run_id": "111",
            },
            {
                "killed": 207,
                "survived": 112,
                "timeout": 0,
                "total": 319,
                "sha": current,
                "run_id": "111",
            },
        ]
        for cached in cached_cases:
            with self.subTest(cached=cached):
                text, metrics = mod.compose_report(
                    cached,
                    profile="light",
                    floor=40.0,
                    timeout_minutes=20,
                    sha=current,
                    run_id="222",
                )
                self.assertIsNone(metrics)
                self.assertIn("Did not score", text)
                self.assertIn("did not score", text)
                self.assertNotIn("Passing", text)
                self.assertNotIn("64.89", text)
                self.assertNotIn("%", text)
                self.assertNotIn("| Killed | 207 |", text)
                self.assertNotIn("| Survived | 112 |", text)
                self.assertNotIn("was not found", text)

    def test_main_does_not_publish_cached_kill_rate(self) -> None:
        mod = _load(
            "write_mutation_pr_report_main", "scripts/ci/write_mutation_pr_report.py"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stats_path = root / "mutmut-cicd-stats.json"
            stats_path.write_text(
                json.dumps(
                    {"killed": 207, "survived": 112, "timeout": 0, "total": 319}
                ),
                encoding="utf-8",
            )
            out = root / "reports" / "mutation-report.md"
            metrics_path = root / "reports" / "mutation-metrics.json"
            metrics_path.parent.mkdir(parents=True)
            metrics_path.write_text("{}\n", encoding="utf-8")
            env = {
                "GITHUB_SHA": "b" * 40,
                "GITHUB_RUN_ID": "222",
                "AVO_MUTATION_PROFILE": "light",
            }
            with patch.dict(os.environ, env, clear=False):
                rc = mod.main(
                    [
                        "--out",
                        str(out),
                        "--stats",
                        str(stats_path),
                        "--profile",
                        "light",
                    ]
                )
            text = out.read_text(encoding="utf-8")
        self.assertEqual(rc, 0)
        self.assertIn("Did not score", text)
        self.assertNotIn("Passing", text)
        self.assertNotIn("64.89", text)
        self.assertNotIn("| Killed | 207 |", text)
        self.assertFalse(metrics_path.exists())

    def test_stamped_current_run_keeps_kill_rate(self) -> None:
        mod = _load(
            "write_mutation_pr_report_stamp", "scripts/ci/write_mutation_pr_report.py"
        )
        sha = "c" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stats_path = root / "mutmut-cicd-stats.json"
            stats_path.write_text(
                json.dumps({"killed": 8, "survived": 2, "timeout": 1, "total": 11}),
                encoding="utf-8",
            )
            out = root / "reports" / "mutation-report.md"
            env = {
                "GITHUB_SHA": sha,
                "GITHUB_RUN_ID": "333",
                "AVO_MUTATION_PROFILE": "light",
            }
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(mod.main(["--stamp", str(stats_path)]), 0)
                rc = mod.main(
                    [
                        "--out",
                        str(out),
                        "--stats",
                        str(stats_path),
                        "--profile",
                        "light",
                    ]
                )
            text = out.read_text(encoding="utf-8")
            metrics = json.loads(
                (root / "reports" / "mutation-metrics.json").read_text(encoding="utf-8")
            )
            stamped = json.loads(stats_path.read_text(encoding="utf-8"))
        self.assertEqual(rc, 0)
        self.assertEqual(stamped["sha"], sha)
        self.assertEqual(stamped["run_id"], "333")
        self.assertEqual(stamped["killed"], 8)
        self.assertIn("80.00%", text)
        self.assertIn("Passing (>= 40)", text)
        self.assertIn("| Killed | 8 |", text)
        self.assertIn("| Survived | 2 |", text)
        self.assertEqual(
            metrics,
            {"floor": 40.0, "killed": 8, "sha": sha, "survived": 2},
        )

    def test_stamped_run_below_floor_stays_failing(self) -> None:
        mod = _load(
            "write_mutation_pr_report_floor", "scripts/ci/write_mutation_pr_report.py"
        )
        sha = "d" * 40
        stats = {
            "killed": 1,
            "survived": 9,
            "timeout": 0,
            "total": 10,
            "sha": sha,
            "run_id": "444",
        }
        text, metrics = mod.compose_report(
            stats,
            profile="light",
            floor=40.0,
            timeout_minutes=20,
            sha=sha,
            run_id="444",
        )
        self.assertIn("10.00%", text)
        self.assertIn("Failing (< 40)", text)
        self.assertNotIn("Did not score", text)
        self.assertNotIn("Passing", text)
        self.assertEqual(metrics["killed"], 1)
        self.assertEqual(metrics["survived"], 9)

    def test_size_signal_summarizes_pack_without_file_dump(self) -> None:
        mod = _load(
            "write_size_signal_report", "scripts/ci/write_size_signal_report.py"
        )
        summary = mod.summarize(
            {
                "filename": "avo-1.4.0.tgz",
                "version": "1.4.0",
                "size": 2 * 1024 * 1024,
                "unpackedSize": 5 * 1024 * 1024,
                "entryCount": 42,
            },
            node_modules_bytes=10 * 1024 * 1024,
        )
        text = mod.build_markdown(summary)
        self.assertIn("## Size signal", text)
        self.assertIn("2.00 MB", text)
        self.assertIn("5.00 MB", text)
        self.assertIn("| Files in pack | 42 |", text)
        self.assertNotIn("Tarball Contents", text)
        self.assertNotIn("<details>", text)

    def test_deps_metric_reads_npm_audit_summary(self) -> None:
        mod = _load("write_quality_pr_report", "scripts/ci/write_quality_pr_report.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = root / "reports" / "quality" / "npm-audit-summary.json"
            summary.parent.mkdir(parents=True)
            summary.write_text(
                json.dumps({"ok": True, "critical": 0, "high": 8}),
                encoding="utf-8",
            )
            metric = mod.gate_metric(
                "deps",
                coverage_json=Path("missing.json"),
                floor=68.0,
                root=root,
            )
            self.assertEqual(metric, "PASS, 0 critical, 8 high reported")

            empty = root / "empty"
            empty.mkdir()
            fallback = mod.gate_metric(
                "deps",
                coverage_json=Path("missing.json"),
                floor=68.0,
                root=empty,
            )
        self.assertEqual(fallback, "0 npm GHSA exceptions")

    def test_duplication_metric_shows_measured_percent_beside_ceiling(self) -> None:
        mod = _load("write_quality_pr_report", "scripts/ci/write_quality_pr_report.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".jscpd.json").write_text(
                json.dumps({"threshold": 2}), encoding="utf-8"
            )
            missing = mod.gate_metric(
                "duplication",
                coverage_json=Path("missing.json"),
                floor=68.0,
                root=root,
            )
            self.assertEqual(missing, "ceiling 2%")
            report = root / "reports" / "quality" / "jscpd" / "jscpd-report.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                json.dumps({"statistics": {"total": {"percentage": 0.97672}}}),
                encoding="utf-8",
            )
            measured = mod.gate_metric(
                "duplication",
                coverage_json=Path("missing.json"),
                floor=68.0,
                root=root,
            )
        self.assertEqual(measured, "0.98% (ceiling 2%)")


if __name__ == "__main__":
    unittest.main()
