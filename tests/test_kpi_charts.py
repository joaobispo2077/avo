"""Phase A Software quality sticky charts: table ≡ chart ≡ source, not a gate."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FAIL_RGB = (176, 0, 32)
PASS_RGB = (27, 127, 58)


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png_series(path: Path) -> dict:
    with Image.open(path) as image:
        raw = image.info.get("Description") or image.info.get("description")
        keys = sorted(image.info)
    if not isinstance(raw, str):
        raise AssertionError(f"missing chart series in {path.name}: {keys}")
    return json.loads(raw)


def _has_color(path: Path, rgb: tuple[int, int, int], tol: int = 12) -> bool:
    with Image.open(path) as image:
        data = image.convert("RGB").tobytes()
    red, green, blue = rgb
    return any(
        abs(data[index] - red) <= tol
        and abs(data[index + 1] - green) <= tol
        and abs(data[index + 2] - blue) <= tol
        for index in range(0, len(data), 3)
    )


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


class KpiChartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.charts = _load("gen_kpi_charts", "scripts/ci/gen_kpi_charts.py")
        self.report = self.charts._report()
        self.host = _load(
            "upload_kpi_chart_images", "scripts/ci/upload_kpi_chart_images.py"
        )

    def _workspace(self) -> Path:
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        return Path(handle.name)

    def _outcomes(self, **overrides: str) -> dict[str, str]:
        outcomes = {key: "success" for key, _title in self.report.GATES}
        outcomes.update(overrides)
        return outcomes

    def test_real_coverage_floor_is_68(self) -> None:
        floor = self.report.coverage_floor_from_pyproject(ROOT / "pyproject.toml")
        self.assertEqual(floor, 68.0)
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("fail_under = 68", pyproject)
        self.assertNotIn("fail_under = 80", pyproject)

    def test_table_chart_and_source_match(self) -> None:
        tmp = self._workspace()
        _fixture_root(tmp)
        coverage = tmp / "coverage.json"
        _coverage(coverage, 71.25, 712, 1000)
        section, snapshot = self.charts.generate(
            self._outcomes(),
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
            out_dir=tmp / "charts",
        )
        self.assertEqual(snapshot["overall"], "PASS")
        self.assertIn("**Overall: PASS**", section)
        self.assertIn("| Line coverage | 71.25% |", section)
        self.assertIn("| Floor (fail_under) | 68% |", section)
        self.assertIn("| Lines | 712/1000 |", section)
        self.assertIn("| Allowlisted blocks | 2 |", section)
        self.assertIn("| Allowlisted items | 1 |", section)
        self.assertIn("| npm GHSA exceptions | 1 |", section)
        self.assertIn("| Ceiling | 2% |", section)
        self.assertIn("| Contracts | 3 |", section)
        self.assertNotIn("80%", section)
        coverage_png = _png_series(tmp / "charts" / "coverage.png")
        self.assertEqual(coverage_png["measured"], 71.25)
        self.assertEqual(coverage_png["floor"], 68.0)
        self.assertEqual(coverage_png["state"], "pass")
        self.assertEqual(coverage_png["covered"], 712)
        self.assertEqual(coverage_png["statements"], 1000)
        self.assertEqual(_png_series(tmp / "charts" / "complexity.png")["count"], 2)
        self.assertEqual(_png_series(tmp / "charts" / "deadcode.png")["count"], 1)
        self.assertEqual(_png_series(tmp / "charts" / "deps.png")["count"], 1)
        self.assertEqual(_png_series(tmp / "charts" / "duplication.png")["ceiling"], 2)
        self.assertEqual(_png_series(tmp / "charts" / "architecture.png")["count"], 3)
        self.assertTrue(
            (tmp / "charts" / "coverage.png").read_bytes().startswith(b"\x89PNG")
        )

    def test_failed_job_is_not_an_all_green_dashboard(self) -> None:
        tmp = self._workspace()
        _fixture_root(tmp)
        coverage = tmp / "coverage.json"
        _coverage(coverage, 90.0, 900, 1000)
        section, snapshot = self.charts.generate(
            self._outcomes(lint="failure", coverage="skipped", format="skipped"),
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
            out_dir=tmp / "charts",
        )
        self.assertEqual(snapshot["overall"], "FAIL")
        self.assertIn("**Overall: FAIL**", section)
        self.assertNotIn("**Overall: PASS**", section)
        self.assertIn("| Lint | **FAIL** |", section)
        self.assertIn("| Coverage | **SKIPPED** |", section)
        self.assertIn("| Line coverage | 90.00% |", section)
        self.assertEqual(_png_series(tmp / "charts" / "coverage.png")["state"], "fail")
        self.assertEqual(_png_series(tmp / "charts" / "status.png")["overall"], "FAIL")
        self.assertTrue(_has_color(tmp / "charts" / "status.png", FAIL_RGB))
        self.assertTrue(_has_color(tmp / "charts" / "coverage.png", FAIL_RGB))

    def test_below_floor_bar_is_red_even_if_steps_passed(self) -> None:
        tmp = self._workspace()
        _fixture_root(tmp)
        coverage = tmp / "coverage.json"
        _coverage(coverage, 50.0, 500, 1000)
        section, snapshot = self.charts.generate(
            self._outcomes(),
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
            out_dir=tmp / "charts",
        )
        self.assertEqual(snapshot["overall"], "PASS")
        self.assertEqual(snapshot["coverage"]["state"], "fail")
        self.assertIn("| Line coverage | 50.00% |", section)
        self.assertIn("| Floor (fail_under) | 68% |", section)
        self.assertTrue(_has_color(tmp / "charts" / "coverage.png", FAIL_RGB))

    def test_missing_coverage_does_not_plot_zero(self) -> None:
        tmp = self._workspace()
        _fixture_root(tmp)
        section, _snapshot = self.charts.generate(
            self._outcomes(coverage="skipped"),
            coverage_json=tmp / "missing.json",
            floor=68.0,
            root=tmp,
            out_dir=tmp / "charts",
        )
        self.assertIn("| Line coverage | — |", section)
        self.assertIn("| Floor (fail_under) | 68% |", section)
        self.assertNotIn("0.00%", section)
        self.assertNotIn("**Overall: PASS**", section)
        series = _png_series(tmp / "charts" / "coverage.png")
        self.assertIsNone(series["measured"])
        self.assertEqual(series["floor"], 68.0)
        self.assertEqual(series["state"], "fail")

    def test_mutation_is_a_dash_not_a_score(self) -> None:
        tmp = self._workspace()
        _fixture_root(tmp)
        section, _snapshot = self.charts.generate(
            self._outcomes(),
            coverage_json=tmp / "missing.json",
            floor=68.0,
            root=tmp,
            out_dir=tmp / "charts",
        )
        mutation = section.split("### Mutation", 1)[1]
        self.assertIn("| Mutation | — |", mutation)
        self.assertIn("`mutation-report`", mutation)
        self.assertNotIn("%", mutation)
        self.assertNotIn("kpi-chart:", mutation)
        self.assertNotIn("![", mutation)

    def test_passed_status_chart_has_no_fail_red(self) -> None:
        tmp = self._workspace()
        _fixture_root(tmp)
        _coverage(tmp / "coverage.json", 71.25, 712, 1000)
        self.charts.generate(
            self._outcomes(),
            coverage_json=tmp / "coverage.json",
            floor=68.0,
            root=tmp,
            out_dir=tmp / "charts",
        )
        status = tmp / "charts" / "status.png"
        self.assertTrue(_has_color(status, PASS_RGB))
        self.assertFalse(_has_color(status, FAIL_RGB))

    def test_upload_rewrites_urls_and_never_leaves_an_empty_image(self) -> None:
        source = (
            "### Coverage\n"
            "\n"
            "![Coverage](kpi-chart:coverage.png)\n"
            "\n"
            "| Field | Value |\n"
            "| Line coverage | 71.25% |"
        )
        hosted = self.host.apply_image_urls(
            source,
            {"coverage.png": "https://github.com/user-attachments/assets/abc"},
            {},
        )
        self.assertIn(
            "![Coverage](https://github.com/user-attachments/assets/abc)",
            hosted,
        )
        self.assertNotIn("kpi-chart:", hosted)
        self.assertNotIn("![](", hosted)
        self.assertIn("71.25%", hosted)

        failed = self.host.apply_image_urls(
            source,
            {},
            {"coverage.png": "user-attachments HTTP 404"},
        )
        self.assertIn("**Chart image unavailable (Coverage):**", failed)
        self.assertIn("71.25%", failed)
        self.assertNotIn("![", failed)
        self.assertNotIn("kpi-chart:", failed)
        self.assertNotIn("![](", failed)

    def test_chart_host_refuses_other_branches(self) -> None:
        self.assertEqual(
            self.host.guarded_branch("ci/quality-kpi-charts"), "ci/quality-kpi-charts"
        )
        with self.assertRaises(ValueError):
            self.host.guarded_branch("feature/avo-kpi-charts")
        with self.assertRaises(ValueError):
            self.host.guarded_branch("develop")
        with self.assertRaises(ValueError):
            self.host.chart_object_path("12", "../secrets.png")
        url = self.host.raw_githubusercontent_url(
            "joaobispo2077/avo",
            "ci/quality-kpi-charts",
            "quality-kpi-charts/12/coverage.png",
        )
        self.assertEqual(
            url,
            "https://raw.githubusercontent.com/joaobispo2077/avo/"
            "ci/quality-kpi-charts/quality-kpi-charts/12/coverage.png",
        )

    def test_failure_note_has_no_image(self) -> None:
        note = self.charts.failure_section("FAIL", "matplotlib missing")
        self.assertIn("**Overall: FAIL**", note)
        self.assertIn("**Chart generation failed:**", note)
        self.assertIn("| Mutation | — |", note)
        self.assertNotIn("![", note)
        self.assertNotIn("![](", note)

    def _without_gate_env(self) -> None:
        saved = {
            f"Q_{key.upper()}": os.environ.pop(f"Q_{key.upper()}", None)
            for key, _title in self.report.GATES
        }

        def restore() -> None:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore)

    def test_sidecar_keeps_chart_pass_when_env_is_empty(self) -> None:
        """Empty Q_* must not turn a PASS report table into FAIL/UNKNOWN charts."""
        self._without_gate_env()
        tmp = self._workspace()
        _fixture_root(tmp)
        coverage = tmp / "coverage.json"
        _coverage(coverage, 71.25, 712, 1000)
        outcomes = self._outcomes()
        table = self.report.build_markdown(
            outcomes,
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
        )
        sidecar = tmp / "gate-outcomes.json"
        self.report.write_gate_outcomes(sidecar, outcomes)
        loaded = self.charts.resolve_outcomes(sidecar)
        section, snapshot = self.charts.generate(
            loaded,
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
            out_dir=tmp / "charts",
        )
        self.assertIn("**Overall: PASS**", table)
        self.assertIn("| Lint | **PASS** |", table)
        self.assertEqual(loaded, outcomes)
        self.assertEqual(snapshot["overall"], self.report.overall_label(outcomes))
        self.assertEqual(snapshot["overall"], "PASS")
        self.assertIn("**Overall: PASS**", section)
        self.assertNotIn("**UNKNOWN**", section)
        self.assertNotIn("**Overall: FAIL**", section)

    def test_env_outcomes_match_table_when_sidecar_is_absent(self) -> None:
        self._without_gate_env()
        for key, _title in self.report.GATES:
            os.environ[f"Q_{key.upper()}"] = "success"
        tmp = self._workspace()
        _fixture_root(tmp)
        coverage = tmp / "coverage.json"
        _coverage(coverage, 71.25, 712, 1000)
        loaded = self.charts.resolve_outcomes(tmp / "gate-outcomes.json")
        table = self.report.build_markdown(
            loaded,
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
        )
        section, snapshot = self.charts.generate(
            loaded,
            coverage_json=coverage,
            floor=68.0,
            root=tmp,
            out_dir=tmp / "charts",
        )
        self.assertEqual(snapshot["overall"], "PASS")
        self.assertEqual(snapshot["overall"], self.report.overall_label(loaded))
        self.assertIn("**Overall: PASS**", table)
        self.assertIn("**Overall: PASS**", section)
        self.assertNotIn("**UNKNOWN**", section)

    def test_upsert_replaces_previous_chart_block(self) -> None:
        once = self.charts.upsert_section("## Software metrics\n", "first")
        twice = self.charts.upsert_section(once, "second")
        self.assertEqual(twice.count("kpi-charts:start"), 1)
        self.assertIn("second", twice)
        self.assertNotIn("first", twice)
        self.assertIn("## Software metrics", twice)
