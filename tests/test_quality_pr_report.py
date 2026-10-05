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

    def _empty_allowlist_root(self) -> Path:
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        root = Path(handle.name)
        allow = root / "scripts" / "ci"
        allow.mkdir(parents=True)
        (allow / "deps-audit-allowlist.json").write_text(
            json.dumps({"npm": {"advisory_ids": []}, "pip": {"ignore_vulns": []}}),
            encoding="utf-8",
        )
        return root

    def _deps_findings(self, root: Path, findings: list[dict]) -> Path:
        path = root / "reports" / "quality" / "deps-findings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"findings": findings}, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def test_deps_fail_without_ghsa_names_package_and_via(self) -> None:
        mod = _load("write_quality_pr_report", "scripts/ci/write_quality_pr_report.py")
        root = self._empty_allowlist_root()
        self._deps_findings(
            root,
            [{"package": "@jscpd/finder", "id": None, "via": "fast-glob"}],
        )
        text = mod.build_markdown(
            {
                "lint": "success",
                "format": "success",
                "coverage": "success",
                "complexity": "success",
                "deps": "failure",
                "deadcode": "skipped",
                "duplication": "skipped",
                "architecture": "skipped",
                "tree": "skipped",
            },
            coverage_json=Path("missing.json"),
            floor=68.0,
            root=root,
        )
        self.assertIn(
            "| Dependency audit | **FAIL** | "
            "@jscpd/finder via fast-glob has no GHSA id |",
            text,
        )
        self.assertNotIn("npm GHSA exceptions", text)
        self.assertEqual(
            mod.gate_metric(
                "deps",
                coverage_json=Path("missing.json"),
                floor=68.0,
                root=root,
            ),
            "0 npm GHSA exceptions",
        )
        self.assertIn("| Dead code | **SKIPPED** |", text)
        self.assertIn("| Duplication | **SKIPPED** |", text)
        self.assertIn("| Architecture | **SKIPPED** |", text)
        self.assertIn("| Dependency tree | **SKIPPED** |", text)
        self.assertIn("**Overall: FAIL**", text)

    def test_deps_pass_with_empty_allowlist_reports_waiver_count(self) -> None:
        mod = _load("write_quality_pr_report", "scripts/ci/write_quality_pr_report.py")
        root = self._empty_allowlist_root()
        self._deps_findings(
            root,
            [{"package": "@jscpd/finder", "id": None, "via": "fast-glob"}],
        )
        text = mod.build_markdown(
            {"deps": "success"},
            coverage_json=Path("missing.json"),
            floor=68.0,
            root=root,
        )
        self.assertIn(
            "| Dependency audit | **PASS** | 0 npm GHSA exceptions |",
            text,
        )
        self.assertNotIn("@jscpd/finder", text)
        self.assertNotIn("fast-glob", text)
        self.assertNotIn("no GHSA id", text)

    def test_deps_fail_lists_every_unwaived_finding(self) -> None:
        mod = _load("write_quality_pr_report", "scripts/ci/write_quality_pr_report.py")
        root = self._empty_allowlist_root()
        self._deps_findings(
            root,
            [
                {"package": "@jscpd/finder", "id": None, "via": "fast-glob"},
                {"package": "minimatch", "id": None, "via": "brace-expansion"},
                {"package": "yaml", "id": None, "via": "lodash"},
            ],
        )
        text = mod.build_markdown(
            {"deps": "failure"},
            coverage_json=Path("missing.json"),
            floor=68.0,
            root=root,
        )
        cell = (
            "@jscpd/finder via fast-glob has no GHSA id; "
            "minimatch via brace-expansion has no GHSA id; "
            "yaml via lodash has no GHSA id"
        )
        self.assertIn(f"| Dependency audit | **FAIL** | {cell} |", text)
        self.assertNotIn("npm GHSA exceptions", text)
        self.assertLess(text.index("@jscpd/finder"), text.index("minimatch"))
        self.assertLess(text.index("minimatch"), text.index("yaml via lodash"))
        self.assertEqual(
            mod.gate_metric(
                "deps",
                coverage_json=Path("missing.json"),
                floor=68.0,
                root=root,
            ),
            "0 npm GHSA exceptions",
        )

    def test_deps_fail_with_advisory_id_names_package_and_id(self) -> None:
        mod = _load("write_quality_pr_report", "scripts/ci/write_quality_pr_report.py")
        root = self._empty_allowlist_root()
        cases = (
            ("ip-address", "GHSA-mwp4-54f8-5fhr"),
            ("requests", "PYSEC-2024-123"),
        )
        for package, advisory in cases:
            self._deps_findings(
                root,
                [{"package": package, "id": advisory, "via": ""}],
            )
            text = mod.build_markdown(
                {"deps": "failure"},
                coverage_json=Path("missing.json"),
                floor=68.0,
                root=root,
            )
            self.assertIn(
                f"| Dependency audit | **FAIL** | {package} {advisory} |",
                text,
            )
            self.assertNotIn("npm GHSA exceptions", text)
            self.assertNotIn("@jscpd/finder", text)

    def test_deps_fail_without_recorded_finding_does_not_invent_one(self) -> None:
        mod = _load("write_quality_pr_report", "scripts/ci/write_quality_pr_report.py")
        root = self._empty_allowlist_root()
        text = mod.build_markdown(
            {"deps": "failure"},
            coverage_json=Path("missing.json"),
            floor=68.0,
            root=root,
        )
        self.assertIn(
            "| Dependency audit | **FAIL** | 0 npm GHSA exceptions |",
            text,
        )
        self.assertNotIn("@jscpd/finder", text)
        self.assertNotIn("fast-glob", text)

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


if __name__ == "__main__":
    unittest.main()
