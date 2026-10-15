"""Release-cut quality metrics snapshot: SHA-bound readout, not a gate."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA = "0123456789abcdef0123" * 2
OTHER = "fedcba9876543210fedc" * 2
RECORDED = "2026-10-02T20:03:00Z"
RUN_ID = "1234567"


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_root(tmp: Path) -> None:
    ci = tmp / "scripts" / "ci"
    ci.mkdir(parents=True)
    (ci / "complexity-allowlist.json").write_text(
        json.dumps({"blocks": [{"name": "a"}, {"name": "b"}]}),
        encoding="utf-8",
    )
    (ci / "deadcode-allowlist.json").write_text(
        json.dumps({"items": [{"name": "only"}]}),
        encoding="utf-8",
    )
    (ci / "deps-audit-allowlist.json").write_text(
        json.dumps({"npm": {"advisory_ids": ["GHSA-test"]}}),
        encoding="utf-8",
    )
    (ci / "mutation-config.json").write_text(
        json.dumps({"light": {"min_killed_percent": 40}}), encoding="utf-8"
    )
    (tmp / ".jscpd.json").write_text(json.dumps({"threshold": 2}), encoding="utf-8")
    (tmp / ".importlinter").write_text(
        "[importlinter:contract:one]\n"
        "[importlinter:contract:two]\n"
        "[importlinter:contract:three]\n",
        encoding="utf-8",
    )
    duplication = tmp / "reports" / "quality" / "jscpd" / "jscpd-report.json"
    duplication.parent.mkdir(parents=True)
    duplication.write_text(
        json.dumps({"statistics": {"total": {"percentage": 1.0}}}),
        encoding="utf-8",
    )


def _coverage(path: Path, percent: float, covered: int, statements: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": percent,
                    "covered_lines": covered,
                    "num_statements": statements,
                }
            }
        ),
        encoding="utf-8",
    )


class QualityMetricsSnapshotTests(unittest.TestCase):
    def test_skipped_dependency_gate_ignores_stale_summary_in_all_views(self) -> None:
        root = self._workspace()
        self._document(root)
        summary = root / "reports" / "quality" / "npm-audit-summary.json"
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(json.dumps({"ok": True, "critical": 0, "high": 99}))
        document = self.mod.build_ci_document(
            self._outcomes(deps="skipped"),
            coverage_json=root / "coverage.json",
            floor=68,
            root=root,
            sha=SHA,
            recorded_at=RECORDED,
        )
        gate = next(row for row in document["gates"] if row["key"] == "deps")
        self.assertEqual(gate["status"], "SKIPPED")
        self.assertEqual(gate["metric"], "not measured")
        self.assertEqual(document["series"]["deps"]["reported"], "not measured")
        self.assertNotIn("99 high", json.dumps(document))

    def setUp(self) -> None:
        self.mod = _load(
            "write_quality_metrics_snapshot",
            "scripts/ci/write_quality_metrics_snapshot.py",
        )
        self.report = self.mod._report()
        self.charts = self.mod._charts()

    def _workspace(self) -> Path:
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        return Path(handle.name)

    def _outcomes(self, **overrides: str) -> dict[str, str]:
        outcomes = {key: "success" for key, _title in self.report.GATES}
        outcomes.update(overrides)
        return outcomes

    def _document(self, tmp: Path, *, legacy: bool = False, **overrides: str) -> dict:
        _fixture_root(tmp)
        coverage = tmp / "coverage.json"
        _coverage(coverage, 71.25, 712, 1000)
        document = self.mod.build_ci_document(
            self._outcomes(**overrides),
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
            sha=SHA,
            recorded_at=RECORDED,
            run_id=RUN_ID,
        )
        if legacy:
            document["schema"] = 1
            document.pop("run_id")
            document.pop("mutation_policy")
            document["series"].pop("dashboard")
            document["overall"] = self.report.overall_label(self._outcomes(**overrides))
            return document
        document["jobs"] = {
            job: "success"
            for job in (
                "prerequisites-gate",
                "repo-unit-tests",
                "repo-integration-tests",
                "software-quality",
                "usability-gate",
                "mutation-light",
                "ci-readiness",
            )
        }
        document["mutation"] = self._mutation()
        document["series"]["dashboard"] = self.mod._dashboard().build_series(document)
        document["overall"] = document["series"]["dashboard"]["overall"]
        return document

    def _mutation(self, **overrides) -> dict:
        mutation = {
            "sha": SHA,
            "run_id": RUN_ID,
            "floor": 40,
            "profile": "light",
            "counts": {"killed": 3, "survived": 1, "total": 4},
        }
        mutation.update(overrides)
        return mutation

    def _write_doc(self, tmp: Path, doc: dict) -> Path:
        path = tmp / "quality-metrics.json"
        path.write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def test_ci_json_matches_sticky_and_does_not_invent_mutation(self) -> None:
        tmp = self._workspace()
        _fixture_root(tmp)
        coverage = tmp / "coverage.json"
        _coverage(coverage, 71.25, 712, 1000)
        outcomes = self._outcomes()
        doc = self.mod.build_ci_document(
            outcomes,
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
            sha=SHA,
            recorded_at=RECORDED,
            run_id=RUN_ID,
        )
        sticky = self.report.build_markdown(
            outcomes, coverage_json=coverage, floor=68.0, root=tmp
        )
        self.assertEqual(doc["sha"], SHA)
        self.assertEqual(doc["recorded_at"], RECORDED)
        self.assertEqual(doc["schema"], 2)
        self.assertEqual(doc["run_id"], RUN_ID)
        self.assertEqual(doc["mutation_policy"], {"profile": "light", "floor": 40})
        self.assertEqual(doc["overall"], "INCOMPLETE")
        self.assertEqual(doc["series"]["dashboard"]["overall"], "INCOMPLETE")
        self.assertIsNone(doc["mutation"])
        self.assertNotIn("killed", json.dumps(doc))
        self.assertNotIn("score", json.dumps(doc))
        for row in doc["gates"]:
            self.assertIn(
                f"| {row['title']} | **{row['status']}** | {row['metric']} |",
                sticky,
            )
            self.assertIn(row["checks"], sticky)
        self.assertEqual(doc["series"]["coverage"]["measured"], 71.25)
        self.assertEqual(doc["series"]["coverage"]["floor"], 68.0)
        self.assertEqual(doc["series"]["complexity"]["count"], 2)

    def test_tables_match_fixture_json(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp, legacy=True)
        metrics = self._write_doc(tmp, doc)
        out = tmp / "docs" / "quality-metrics.md"
        text = self.mod.write_snapshot(
            metrics,
            sha=SHA,
            version="1.2.3",
            out=out,
        )
        self.assertIn("| Version | 1.2.3 |", text)
        self.assertIn("| Tag | v1.2.3 |", text)
        self.assertIn(f"| SHA | `{SHA}` |", text)
        self.assertIn(f"| Recorded (UTC) | {RECORDED} |", text)
        self.assertIn("**Overall: PASS**", text)
        for row in doc["gates"]:
            line = (
                f"| {row['title']} | **{row['status']}** | "
                f"{row['metric']} | {row['checks']} |"
            )
            self.assertIn(line, text)
        self.assertIn("| Line coverage | 71.25% |", text)
        self.assertIn("| Floor (fail_under) | 68% |", text)
        self.assertIn("| Lines | 712/1000 |", text)
        self.assertIn("| Allowlisted blocks | 2 |", text)
        self.assertIn("| Ceiling | 2% |", text)
        self.assertIn("| Contracts | 3 |", text)
        mutation = text.split("### Mutation", 1)[1]
        self.assertIn("| Mutation | \u2014 |", mutation)
        self.assertIn("see Mutation sticky", mutation)
        self.assertNotIn("%", mutation)

    def test_schema_two_readout_uses_shared_dashboard_and_collapsed_diagnostics(
        self,
    ) -> None:
        tmp = self._workspace()
        doc = self._document(tmp)
        text = self.mod.write_snapshot(
            self._write_doc(tmp, doc),
            sha=SHA,
            version="1.2.3",
            out=tmp / "quality-metrics.md",
            expected_run_id=RUN_ID,
        )
        for field in ("Version", "Tag", "SHA", "Recorded (UTC)"):
            self.assertIn(f"| {field} |", text)
        self.assertIn("<summary>Metric diagnostics and artifacts</summary>", text)
        self.assertIn("<summary>Execution results</summary>", text)
        self.assertIn("| Gate | Decision | Policy | Execution evidence |", text)
        self.assertIn("| Metric | Measured | Scope | Evidence |", text)
        self.assertNotIn("| Metric | Measured | Threshold | Status |", text)
        self.assertIn("| Coverage | 71.25% | unit-suite line coverage;", text)
        self.assertIn(
            "| Coverage | **PASS** | pytest-cov fail-under on `src/avo`; Minimum 68% |",
            text,
        )
        self.assertIn("| Duplication | 1.00% | duplicated source lines;", text)
        self.assertIn(
            "| Duplication | **PASS** | jscpd on `src/avo`; Maximum 2% |", text
        )
        self.assertIn("| Mutation | 75.00% | light profile;", text)
        self.assertIn("| Mutation | **PASS** | Complete accounting; Minimum 40%;", text)
        self.assertNotIn("### Complexity allowlist", text)
        self.assertNotIn("### Gate status", text)
        self.assertNotIn("![", text)

    def test_schema_two_mutation_requires_complete_counts_and_matching_run(
        self,
    ) -> None:
        self.assertEqual(
            self.mod.mutation_view(
                self._mutation(), SHA, RUN_ID, {"profile": "light", "floor": 40}
            )["score"],
            75,
        )
        invalid = (
            self._mutation(sha=OTHER),
            self._mutation(run_id="another-run"),
            {"sha": SHA, "run_id": RUN_ID, "floor": 40, "score": 99.9},
            self._mutation(
                counts={"killed": 1, "survived": 0, "total": 100, "timeout": 99}
            ),
            self._mutation(counts={"killed": 10, "survived": 0, "total": 1}),
            self._mutation(counts={"killed": True, "survived": 0, "total": 1}),
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertIsNone(
                    self.mod.mutation_view(
                        payload, SHA, RUN_ID, {"profile": "light", "floor": 40}
                    )
                )

    def test_current_mutation_cannot_change_the_frozen_policy(self) -> None:
        policy = {"profile": "light", "floor": 40}
        for payload in (
            self._mutation(profile="full"),
            self._mutation(profile="unknown"),
            self._mutation(floor=0),
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(self.mod.mutation_view(payload, SHA, RUN_ID, policy))

    def test_missing_or_unknown_snapshot_policy_cannot_be_green(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp)
        for policy in (None, {}, {"profile": "unknown", "floor": 40}):
            broken = json.loads(json.dumps(doc))
            broken["mutation_policy"] = policy
            with (
                self.subTest(policy=policy),
                self.assertRaisesRegex(self.mod.SnapshotError, "mutation_policy"),
            ):
                self.mod.write_snapshot(
                    self._write_doc(tmp, broken),
                    sha=SHA,
                    version="1.2.3",
                    out=tmp / "quality-metrics.md",
                    expected_run_id=RUN_ID,
                )
        self.assertFalse((tmp / "quality-metrics.md").exists())

    def test_policy_is_frozen_and_snapshot_does_not_read_current_config(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp)
        (tmp / "scripts" / "ci" / "mutation-config.json").write_text(
            json.dumps({"light": {"min_killed_percent": 90}}), encoding="utf-8"
        )
        text = self.mod.write_snapshot(
            self._write_doc(tmp, doc),
            sha=SHA,
            version="1.2.3",
            out=tmp / "quality-metrics.md",
            expected_run_id=RUN_ID,
        )
        self.assertIn("| Mutation | 75.00% | light profile;", text)
        self.assertIn("| Mutation | **PASS** | Complete accounting; Minimum 40%;", text)

    def test_producer_cannot_invent_a_missing_policy(self) -> None:
        tmp = self._workspace()
        self._document(tmp)
        (tmp / "scripts" / "ci" / "mutation-config.json").unlink()
        with self.assertRaisesRegex(
            self.mod.SnapshotError, "mutation policy unavailable"
        ):
            self.mod.build_ci_document(
                self._outcomes(),
                coverage_json=tmp / "coverage.json",
                floor=68,
                root=tmp,
                sha=SHA,
                recorded_at=RECORDED,
                run_id=RUN_ID,
            )

    def test_snapshot_requires_successful_readiness_job(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp)
        for result in (None, "skipped", "cancelled", "failure", "unknown"):
            broken = json.loads(json.dumps(doc))
            if result is None:
                del broken["jobs"]["ci-readiness"]
            else:
                broken["jobs"]["ci-readiness"] = result
            with self.subTest(result=result), self.assertRaises(self.mod.SnapshotError):
                self.mod.write_snapshot(
                    self._write_doc(tmp, broken),
                    sha=SHA,
                    version="1.2.3",
                    out=tmp / "quality-metrics.md",
                    expected_run_id=RUN_ID,
                )
        self.assertFalse((tmp / "quality-metrics.md").exists())

    def test_schema_one_cannot_validate_a_current_run(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp, legacy=True)
        with self.assertRaisesRegex(self.mod.SnapshotError, "legacy quality metrics"):
            self.mod.write_snapshot(
                self._write_doc(tmp, doc),
                sha=SHA,
                version="1.2.3",
                out=tmp / "quality-metrics.md",
                expected_run_id=RUN_ID,
            )
        self.assertFalse((tmp / "quality-metrics.md").exists())

    def test_schema_two_rejects_tampered_dashboard_before_writing(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp)
        doc["series"]["dashboard"]["metrics"][0]["measured"] = 99.9
        out = tmp / "quality-metrics.md"
        out.write_text("keep\n", encoding="utf-8")
        with self.assertRaisesRegex(
            self.mod.SnapshotError, "does not match its evidence"
        ):
            self.mod.write_snapshot(
                self._write_doc(tmp, doc), sha=SHA, version="1.2.3", out=out
            )
        self.assertEqual(out.read_text(encoding="utf-8"), "keep\n")

    def test_schema_two_rejects_untrusted_mutation_and_missing_mandatory_job(
        self,
    ) -> None:
        tmp = self._workspace()
        doc = self._document(tmp)
        for problem in ("mutation", "jobs"):
            broken = json.loads(json.dumps(doc))
            if problem == "mutation":
                broken["mutation"]["run_id"] = "another-run"
            else:
                del broken["jobs"]["repo-integration-tests"]
            with (
                self.subTest(problem=problem),
                self.assertRaises(self.mod.SnapshotError),
            ):
                self.mod.write_snapshot(
                    self._write_doc(tmp, broken),
                    sha=SHA,
                    version="1.2.3",
                    out=tmp / "quality-metrics.md",
                )
        self.assertFalse((tmp / "quality-metrics.md").exists())

    def test_schema_two_requires_the_expected_run_id(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp)
        with self.assertRaisesRegex(self.mod.SnapshotError, "run_id mismatch"):
            self.mod.write_snapshot(
                self._write_doc(tmp, doc),
                sha=SHA,
                version="1.2.3",
                out=tmp / "quality-metrics.md",
                expected_run_id="another-run",
            )

    def test_release_rejects_malformed_or_unbound_measurement_extension(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp)
        collector = self.mod._measurements()
        capture = collector.collect(doc, tmp / "missing-captures")
        for evidence in (None, {"schema": 2}, {**capture, "metrics": []}):
            with self.subTest(evidence=evidence):
                doc["measurement_evidence"] = evidence
                with self.assertRaisesRegex(
                    self.mod.SnapshotError, "measurement evidence"
                ):
                    self.mod._validate(doc, SHA, "1.2.3", RUN_ID)
        doc["measurement_evidence"] = capture
        doc["series"]["dashboard"] = self.mod._dashboard().build_series(doc)
        with self.assertRaisesRegex(self.mod.SnapshotError, "dashboard is not green"):
            self.mod._validate(doc, SHA, "1.2.3", RUN_ID)

    def test_new_capture_freezes_configured_coverage_precision(self) -> None:
        tmp = self._workspace()
        _fixture_root(tmp)
        config = tmp / "pyproject.toml"
        config.write_text("[tool.coverage.report]\nfail_under = 68\nprecision = 2\n")
        coverage = tmp / "coverage.json"
        _coverage(coverage, 71.25, 712, 1000)
        doc = self.mod.build_ci_document(
            self._outcomes(),
            coverage_json=coverage,
            floor=68,
            root=tmp,
            sha=SHA,
            recorded_at=RECORDED,
            run_id=RUN_ID,
            collect_evidence=True,
        )
        config.write_text("[tool.coverage.report]\nfail_under = 68\nprecision = 0\n")
        self.assertEqual(doc["coverage_precision"], 2)
        self.assertFalse((tmp / "quality-metrics.md").exists())

    def test_missing_json_fails_and_leaves_the_doc_untouched(self) -> None:
        tmp = self._workspace()
        out = tmp / "docs" / "quality-metrics.md"
        out.parent.mkdir(parents=True)
        out.write_text("OLD 99.99%\n", encoding="utf-8")
        with self.assertRaises(self.mod.SnapshotError) as caught:
            self.mod.write_snapshot(
                tmp / "missing.json",
                sha=SHA,
                version="1.2.3",
                out=out,
            )
        self.assertIn("missing", str(caught.exception))
        self.assertEqual(out.read_text(encoding="utf-8"), "OLD 99.99%\n")

    def test_sha_mismatch_fails_and_does_not_stamp_the_old_tip(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp)
        metrics = self._write_doc(tmp, doc)
        out = tmp / "docs" / "quality-metrics.md"
        out.parent.mkdir(parents=True)
        out.write_text("previous release 12.00%\n", encoding="utf-8")
        with self.assertRaises(self.mod.SnapshotError) as caught:
            self.mod.write_snapshot(
                metrics,
                sha=OTHER,
                version="1.2.3",
                out=out,
            )
        self.assertIn("SHA mismatch", str(caught.exception))
        self.assertIn(OTHER, str(caught.exception))
        self.assertEqual(out.read_text(encoding="utf-8"), "previous release 12.00%\n")
        self.assertFalse((tmp / "docs" / "quality" / "charts").exists())

    def test_non_green_json_fails(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp, lint="failure")
        self.assertEqual(doc["overall"], "FAIL")
        metrics = self._write_doc(tmp, doc)
        out = tmp / "quality-metrics.md"
        with self.assertRaises(self.mod.SnapshotError) as caught:
            self.mod.write_snapshot(
                metrics,
                sha=SHA,
                version="1.2.3",
                out=out,
            )
        self.assertIn("not green", str(caught.exception))
        self.assertFalse(out.exists())

    def test_bare_mutation_score_is_not_used(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp, legacy=True)
        doc["mutation"] = {"sha": SHA, "score": 99.9}
        metrics = self._write_doc(tmp, doc)
        side = tmp / "mutation-metrics.json"
        side.write_text(
            json.dumps({"sha": SHA, "score": 88.0}),
            encoding="utf-8",
        )
        text = self.mod.write_snapshot(
            metrics,
            sha=SHA,
            version="1.2.3",
            out=tmp / "quality-metrics.md",
            mutation_path=side,
        )
        mutation = text.split("### Mutation", 1)[1]
        self.assertIn("\u2014", mutation)
        self.assertNotIn("99.9", text)
        self.assertNotIn("88.0", text)
        self.assertNotIn("%", mutation)

    def test_mutation_counts_for_the_same_sha_are_shown(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp, legacy=True)
        metrics = self._write_doc(tmp, doc)
        side = tmp / "mutation-metrics.json"
        side.write_text(
            json.dumps(
                {
                    "sha": SHA,
                    "killed": 3,
                    "survived": 1,
                    "floor": 40,
                    "score": 99.9,
                }
            ),
            encoding="utf-8",
        )
        text = self.mod.write_snapshot(
            metrics,
            sha=SHA,
            version="1.2.3",
            out=tmp / "quality-metrics.md",
            mutation_path=side,
        )
        mutation = text.split("### Mutation", 1)[1]
        self.assertIn("| Mutation | 75.00% (killed 3, survived 1) |", mutation)
        self.assertIn("| Killed | 3 |", mutation)
        self.assertIn("| Survived | 1 |", mutation)
        self.assertNotIn("99.9", text)

    def test_mutation_from_another_sha_is_a_dash(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp, legacy=True)
        metrics = self._write_doc(tmp, doc)
        side = tmp / "mutation-metrics.json"
        side.write_text(
            json.dumps({"sha": OTHER, "killed": 9, "survived": 1, "floor": 40}),
            encoding="utf-8",
        )
        text = self.mod.write_snapshot(
            metrics,
            sha=SHA,
            version="1.2.3",
            out=tmp / "quality-metrics.md",
            mutation_path=side,
        )
        mutation = text.split("### Mutation", 1)[1]
        self.assertIn("\u2014", mutation)
        self.assertNotIn("90.00%", text)
        self.assertNotIn("| Killed | 9 |", text)

    def test_pngs_must_match_json_series(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp)
        metrics = self._write_doc(tmp, doc)
        coverage = tmp / "coverage.json"
        chart_dir = tmp / "charts"
        _snapshot_section, snapshot = self.charts.generate_dashboard(
            self._outcomes(),
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
            out_dir=chart_dir,
            document=doc,
        )
        self.assertEqual(snapshot["series"], doc["series"])
        for key, name in self.mod.CHART_FILES:
            self.assertEqual(self.mod._png_series(chart_dir / name), doc["series"][key])
        out = tmp / "docs" / "quality-metrics.md"
        dest = tmp / "docs" / "quality" / "charts" / "1.2.3"
        text = self.mod.write_snapshot(
            metrics,
            sha=SHA,
            version="1.2.3",
            out=out,
            charts_src=chart_dir,
            charts_dir=dest,
        )
        self.assertIn("quality/charts/1.2.3/dashboard.png", text)
        self.assertEqual(text.count("!["), 1)
        self.assertTrue((dest / "dashboard.png").is_file())
        self.assertEqual(
            self.mod._png_series(dest / "dashboard.png"),
            doc["series"]["dashboard"],
        )
        for row in doc["gates"]:
            self.assertIn(row["metric"], text)
        broken = chart_dir / "dashboard.png"
        self.mod._dashboard().render(
            {**doc["series"]["dashboard"], "sha": OTHER}, broken
        )
        rejected = tmp / "docs" / "rejected.md"
        rejected.write_text("keep\n", encoding="utf-8")
        with self.assertRaises(self.mod.SnapshotError) as caught:
            self.mod.write_snapshot(
                metrics,
                sha=SHA,
                version="1.2.3",
                out=rejected,
                charts_src=chart_dir,
                charts_dir=tmp / "rejected-charts" / "1.2.3",
            )
        self.assertIn("does not match", str(caught.exception))
        self.assertEqual(rejected.read_text(encoding="utf-8"), "keep\n")

    def test_schema_one_retains_exact_seven_chart_validation(self) -> None:
        tmp = self._workspace()
        doc = self._document(tmp, legacy=True)
        chart_dir = tmp / "charts"
        _, snapshot = self.charts.generate(
            self._outcomes(),
            coverage_json=tmp / "coverage.json",
            floor=68.0,
            root=tmp,
            out_dir=chart_dir,
        )
        self.assertEqual(self.mod.chart_series(snapshot), doc["series"])
        metrics = self._write_doc(tmp, doc)
        out = tmp / "docs" / "quality-metrics.md"
        dest = tmp / "docs" / "quality" / "charts" / "1.2.3"
        text = self.mod.write_snapshot(
            metrics,
            sha=SHA,
            version="1.2.3",
            out=out,
            charts_src=chart_dir,
            charts_dir=dest,
        )
        self.assertEqual(text.count("!["), 7)
        for key, name in self.mod.LEGACY_CHART_FILES:
            self.assertEqual(self.mod._png_series(dest / name), doc["series"][key])
        (chart_dir / "coverage.png").unlink()
        with self.assertRaisesRegex(
            self.mod.SnapshotError, "partial quality chart set"
        ):
            self.mod.write_snapshot(
                metrics,
                sha=SHA,
                version="1.2.3",
                out=out,
                charts_src=chart_dir,
                charts_dir=dest,
            )
        self.assertEqual(out.read_text(encoding="utf-8"), text)

    def test_cli_missing_json_exits_nonzero(self) -> None:
        tmp = self._workspace()
        out = tmp / "quality-metrics.md"
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/ci/write_quality_metrics_snapshot.py"),
                "--metrics",
                str(tmp / "nope.json"),
                "--sha",
                SHA,
                "--version",
                "1.2.3",
                "--out",
                str(out),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing", proc.stderr)
        self.assertFalse(out.exists())

    def test_release_workflow_hard_fails_and_prs_do_not_write_the_doc(self) -> None:
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("snapshot-release-quality-metrics.sh", release)
        self.assertEqual(release.count("snapshot-release-quality-metrics.sh"), 1)
        self.assertLess(
            release.index("snapshot-release-quality-metrics.sh"),
            release.index("npm run release"),
        )
        jobs = release.split("jobs:", 1)[1]
        snapshot_job = jobs.split("snapshot-quality-metrics:", 1)[1].split(
            "\n  release:", 1
        )[0]
        publish_job = jobs.split("\n  release:", 1)[1]
        snapshot_header = snapshot_job.split("steps:", 1)[0]
        if_lines = [
            line.strip()
            for line in snapshot_header.splitlines()
            if line.strip().startswith("if:")
        ]
        self.assertEqual(
            if_lines,
            ["if: needs.determine-version.result == 'success'"],
        )
        self.assertIn(
            "ref: ${{ needs.determine-version.outputs.release-sha }}",
            snapshot_job,
        )
        self.assertIn(
            "No releasable version. docs/quality-metrics.md is not written.",
            snapshot_job,
        )
        self.assertNotIn("snapshot-release-quality-metrics.sh", publish_job)
        self.assertIn(
            "if: needs.determine-version.outputs.next-version != ''",
            publish_job.split("steps:", 1)[0],
        )
        self.assertIn("release-quality-snapshot", publish_job)
        self.assertIn("release-sha", publish_job)
        script_at = snapshot_job.index("snapshot-release-quality-metrics.sh")
        self.assertIn(
            "needs.determine-version.outputs.next-version != ''",
            snapshot_job[max(0, script_at - 500) : script_at],
        )
        step = release.split("Snapshot release quality metrics", 1)[1].split(
            "- name: Release", 1
        )[0]
        self.assertNotIn("continue-on-error", step)
        shell = (ROOT / "scripts/ci/snapshot-release-quality-metrics.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("set -euo pipefail", shell)
        self.assertIn("--name quality-metrics", shell)
        self.assertNotIn("|| true", shell)
        self.assertNotIn("exit 0", shell)
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("docs/quality-metrics.md", ci)
        self.assertNotIn("snapshot-release-quality-metrics.sh", ci)
        producer = ci.split("  software-quality:\n", 1)[1].split(
            "  usability-gate:\n", 1
        )[0]
        self.assertNotIn("refs/heads/release", producer)
        self.assertIn("--write-json reports/quality/quality-metrics.json", ci)
        unified = ci.split("  quality-report:\n", 1)[1]
        self.assertIn("if: always()", unified)
        self.assertIn("write_unified_quality_report.py", unified)
        self.assertIn("name: quality-metrics", unified)
        self.assertIn("if-no-files-found: error", unified)
        self.assertIn('--run-id "$RUN_ID"', shell)
        config = (ROOT / "release.config.mjs").read_text(encoding="utf-8")
        self.assertIn("docs/quality-metrics.md", config)
        self.assertIn("docs/quality/charts/**/*.png", config)
        docs = (ROOT / "docs/ci.md").read_text(encoding="utf-8")
        self.assertIn("exact tip", docs.lower())
        self.assertIn("fails the job", docs)
        template = (ROOT / "docs/templates/quality-metrics.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("does not invent", template)

    def test_write_json_cli_binds_env_sha(self) -> None:
        tmp = self._workspace()
        _fixture_root(tmp)
        _coverage(tmp / "coverage.json", 71.25, 712, 1000)
        out = tmp / "quality-metrics.json"
        env = os.environ.copy()
        env["GITHUB_SHA"] = SHA
        env["GITHUB_RUN_ID"] = RUN_ID
        env.pop("GITHUB_ACTIONS", None)
        for key, _title in self.report.GATES:
            env[f"Q_{key.upper()}"] = "success"
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/ci/write_quality_metrics_snapshot.py"),
                "--write-json",
                str(out),
                "--coverage",
                str(tmp / "coverage.json"),
                "--root",
                str(tmp),
                "--floor",
                "68",
                "--recorded-at",
                RECORDED,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["sha"], SHA)
        self.assertEqual(doc["run_id"], RUN_ID)
        self.assertIsNone(doc["mutation"])
        self.assertEqual(doc["overall"], "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
