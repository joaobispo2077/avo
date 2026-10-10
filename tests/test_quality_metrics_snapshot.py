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
    (tmp / ".jscpd.json").write_text(json.dumps({"threshold": 2}), encoding="utf-8")
    (tmp / ".importlinter").write_text(
        "[importlinter:contract:one]\n"
        "[importlinter:contract:two]\n"
        "[importlinter:contract:three]\n",
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
        summary.parent.mkdir(parents=True)
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

    def _document(self, tmp: Path, **overrides: str) -> dict:
        _fixture_root(tmp)
        coverage = tmp / "coverage.json"
        _coverage(coverage, 71.25, 712, 1000)
        return self.mod.build_ci_document(
            self._outcomes(**overrides),
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
            sha=SHA,
            recorded_at=RECORDED,
        )

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
        )
        sticky = self.report.build_markdown(
            outcomes, coverage_json=coverage, floor=68.0, root=tmp
        )
        self.assertEqual(doc["sha"], SHA)
        self.assertEqual(doc["recorded_at"], RECORDED)
        self.assertEqual(doc["overall"], "PASS")
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
        doc = self._document(tmp)
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
        doc = self._document(tmp)
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
        doc = self._document(tmp)
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
        doc = self._document(tmp)
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
        _snapshot_section, snapshot = self.charts.generate(
            self._outcomes(),
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
            out_dir=chart_dir,
        )
        self.assertEqual(self.mod.chart_series(snapshot), doc["series"])
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
        self.assertIn("quality/charts/1.2.3/coverage.png", text)
        self.assertTrue((dest / "coverage.png").is_file())
        self.assertEqual(
            self.mod._png_series(dest / "coverage.png"),
            doc["series"]["coverage"],
        )
        for row in doc["gates"]:
            self.assertIn(row["metric"], text)
        broken = chart_dir / "coverage.png"
        broken.write_bytes((chart_dir / "status.png").read_bytes())
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
        self.assertIn("github.ref == 'refs/heads/release'", ci)
        self.assertIn("--write-json reports/quality/quality-metrics.json", ci)
        self.assertIn("name: quality-metrics", ci)
        self.assertIn("if-no-files-found: error", ci)
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
        self.assertIsNone(doc["mutation"])
        self.assertEqual(doc["overall"], "PASS")


if __name__ == "__main__":
    unittest.main()
