"""The default report is compact, evidence-bound and useful without images."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def dashboard():
    spec = importlib.util.spec_from_file_location(
        "quality_dashboard", ROOT / "scripts/ci/quality_dashboard.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def document(**changes):
    doc = {
        "sha": SHA,
        "run_id": "42",
        "recorded_at": "2026-10-14T12:00:00Z",
        "overall": "PASS",
        "gates": [
            {"key": "coverage", "title": "Coverage", "status": "PASS"},
            {"key": "duplication", "title": "Duplication", "status": "PASS"},
        ],
        "series": {
            "coverage": {"measured": 71.25, "floor": 68},
            "duplication": {"measured": 1.0, "ceiling": 2},
        },
        "mutation": None,
        "mutation_policy": {"profile": "light", "floor": 40},
    }
    doc.update(changes)
    return doc


def test_raw_values_and_one_dashboard(tmp_path):
    mod = dashboard()
    series = mod.build_series(document())
    assert series["metrics"][1]["measured"] == 1.0
    assert series["metrics"][1]["direction"] == "maximum"
    png = tmp_path / "dashboard.png"
    mod.render(series, png)
    assert png.is_file()
    text = mod.markdown(document(), series, image="kpi-chart:dashboard.png")
    assert text.count("![") == 1
    assert "1.00%" in text and "71.25%" in text
    assert "99.00" not in text
    assert "<details>" in text
    assert SHA in text and "42" in text
    assert "UNAVAILABLE" in text


@pytest.mark.parametrize("status", ["SKIPPED", "CANCELLED", "UNKNOWN"])
def test_unexecuted_steps_do_not_reuse_measurements(status):
    doc = document()
    doc["gates"][0]["status"] = status
    series = dashboard().build_series(doc)
    assert series["metrics"][0]["measured"] is None
    assert series["metrics"][0]["status"] == status
    assert series["overall"] != "PASS"


def test_claimed_pass_below_floor_is_reported_as_failure():
    doc = document()
    doc["series"]["coverage"]["measured"] = 50
    series = dashboard().build_series(doc)
    assert series["overall"] == "FAIL"
    assert series["metrics"][0]["status"] == "FAIL"
    assert any("Coverage" in item for item in series["actions"])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 101, True])
def test_invalid_percentages_never_look_successful(value):
    doc = document()
    doc["series"]["coverage"]["measured"] = value
    metric = dashboard().build_series(doc)["metrics"][0]
    assert metric["measured"] is None
    assert metric["status"] == "UNAVAILABLE"


def test_missing_image_keeps_measurements_and_actions():
    doc = document(overall="FAIL")
    mod = dashboard()
    series = mod.build_series(doc)
    text = mod.markdown(doc, series)
    assert "![" not in text
    assert "71.25%" in text
    assert "**Overall: FAIL**" in text


def test_mutation_needs_current_run_and_complete_counts():
    doc = document()
    doc["mutation"] = {
        "sha": SHA,
        "run_id": "42",
        "profile": "light",
        "floor": 40,
        "killed": 3,
        "survived": 1,
        "total": 4,
    }
    mod = dashboard()
    metric = mod.build_series(doc)["metrics"][2]
    assert metric["measured"] == 75
    doc["mutation"]["run_id"] = "41"
    assert mod.build_series(doc)["metrics"][2]["measured"] is None
    doc["mutation"]["run_id"] = "42"
    doc["mutation"].update(total=5, timeout=1)
    metric = mod.build_series(doc)["metrics"][2]
    assert metric["measured"] is None
    assert metric["status"] == "INCOMPLETE"


def test_png_embeds_exact_series(tmp_path):
    from PIL import Image

    mod = dashboard()
    series = mod.build_series(document())
    png = tmp_path / "dashboard.png"
    mod.render(series, png)
    with Image.open(png) as image:
        assert json.loads(image.info["Description"]) == series


def test_profile_and_floor_must_match_frozen_policy():
    doc = document()
    doc["mutation"] = {
        "sha": SHA,
        "run_id": "42",
        "floor": 0,
        "killed": 0,
        "survived": 1,
        "total": 1,
    }
    assert dashboard().build_series(doc)["metrics"][2]["status"] == "UNAVAILABLE"


def test_missing_required_jobs_prevents_green_report():
    doc = document()
    doc["mutation"] = {
        "sha": SHA,
        "run_id": "42",
        "profile": "light",
        "floor": 40,
        "killed": 3,
        "survived": 1,
        "total": 4,
    }
    assert dashboard().build_series(doc)["overall"] == "INCOMPLETE"


def test_default_chart_cli_emits_one_dashboard(tmp_path, monkeypatch):
    import sys

    from scripts.ci import gen_kpi_charts as charts
    from scripts.ci.write_quality_pr_report import GATES

    (tmp_path / "pyproject.toml").write_text(
        "[tool.coverage.report]\nfail_under = 68\n"
    )
    (tmp_path / ".jscpd.json").write_text('{"threshold": 2}')
    ci = tmp_path / "scripts" / "ci"
    ci.mkdir(parents=True)
    (ci / "mutation-config.json").write_text('{"light": {"min_killed_percent": 40}}')
    report = tmp_path / "report.md"
    (tmp_path / "gate-outcomes.json").write_text(
        json.dumps({"gates": {key: "success" for key, _ in GATES}})
    )
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": 71,
                    "covered_lines": 71,
                    "num_statements": 100,
                }
            }
        )
    )
    out = tmp_path / "charts"
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gen_kpi_charts.py",
            "--append",
            str(report),
            "--coverage",
            str(coverage),
            "--root",
            str(tmp_path),
            "--out-dir",
            str(out),
        ],
    )
    assert charts.main() == 0
    assert [path.name for path in out.glob("*.png")] == ["dashboard.png"]
    assert report.read_text().count("![") == 1


def test_plot_failure_retains_text_table(tmp_path, monkeypatch):
    from scripts.ci import gen_kpi_charts as charts

    def unavailable(*args):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(charts.dashboard_module(), "render", unavailable)
    text, _ = charts.generate_dashboard(
        {},
        coverage_json=tmp_path / "missing",
        floor=68,
        root=tmp_path,
        out_dir=tmp_path / "charts",
        document=document(),
    )
    assert "71.25%" in text
    assert "Minimum 68%" in text
    assert "![" not in text
    assert "Measurements remain in the table" in text
