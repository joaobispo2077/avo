"""The default report is compact, evidence-bound and useful without images."""

from __future__ import annotations

import hashlib
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


def measured_document():
    titles = {
        "coverage": "Line coverage",
        "duplication": "Duplication",
        "mutation": "Mutation efficacy",
        "complexity": "Cyclomatic complexity",
        "crap": "CRAP",
        "coupling": "Coupling (CA / CE)",
        "dependencies": "Dependency findings",
        "deadcode": "Dead-code findings",
        "architecture": "Import boundaries",
        "tree": "Dependency hoist plan",
        "branches": "Safety branch coverage",
    }
    metrics = [
        {
            "key": key,
            "title": title,
            "state": "MEASURED",
            "value": "Measured finding",
            "number": None,
            "unit": None,
            "scope": "src/avo",
            "basis": "Verified analyzer output.",
            "sources": [
                {
                    "artifact": "quality-evidence",
                    "path": f"{key}.json",
                    "sha256": hashlib.sha256(key.encode()).hexdigest(),
                }
            ],
        }
        for key, title in titles.items()
    ]
    for row, number in zip(metrics[:2], (63.0, 0.75), strict=True):
        row.update(number=number, value=f"{number:.2f}%", unit="percent")
    doc = document(
        repository="owner/avo",
        artifact_urls={
            "quality-evidence": "https://github.com/owner/avo/actions/runs/42/artifacts/7"
        },
        jobs={"repo-unit-tests": "success", "repo-integration-tests": "success"},
        measurement_evidence={
            "schema": 1,
            "metrics": metrics,
            "gates": {
                key: {"verified": True, "sources": []}
                for key in ("coverage", "duplication")
            },
            "diagnostics": {
                "code_risk": {
                    "functions": [
                        {
                            "path": "src/avo/sample.py",
                            "line": 17,
                            "qualname": "Service.choose",
                            "complexity": 7,
                            "function_coverage": {"percent": 50},
                            "crap": {"value": 13.125},
                        }
                    ]
                }
            },
        },
        test_evidence={
            "repo-unit-tests": {
                "state": "PARTIAL",
                "counts": {
                    "total": 4,
                    "passed": 2,
                    "failed": 1,
                    "errors": 0,
                    "skipped": 1,
                },
                "sources": [],
            },
            "repo-integration-tests": {"state": "UNAVAILABLE", "counts": None},
        },
    )
    return doc


def test_measurements_gates_and_execution_have_distinct_evidence():
    doc = measured_document()
    mod = dashboard()
    text = mod.markdown(doc, mod.build_series(doc))
    observations = text.split("**Measurements**", 1)[1].split("**Gate decisions**", 1)[
        0
    ]
    decisions = text.split("**Gate decisions**", 1)[1].split(
        "<summary>Execution results</summary>", 1
    )[0]
    execution = text.split("<summary>Execution results</summary>", 1)[1].split(
        "</details>", 1
    )[0]
    assert "**PASS**" not in observations and "SUCCESS" not in observations
    assert "**PASS**" in decisions and "Minimum 68%" in decisions
    assert "2 passed / 1 failed / 0 errors / 1 skipped; 4 JUnit testcases" in execution
    assert "PARTIAL:" in execution and "UNAVAILABLE:" in execution
    assert "testcase counts not captured" in execution
    assert "0 JUnit testcases" not in execution
    for row in doc["measurement_evidence"]["metrics"]:
        source = row["sources"][0]
        assert f"| {row['title']} |" in observations
        assert (
            f"[{source['path']}]({doc['artifact_urls']['quality-evidence']})"
            in observations
        )
        assert f"SHA-256 `{source['sha256'][:12]}`" in observations
    assert f"https://github.com/owner/avo/blob/{SHA}/src/avo/sample.py#L17" in text
    assert "CRAP reference 30 is informational" in text


def test_normalized_values_replace_cached_series_in_plot():
    doc = measured_document()
    series = dashboard().build_series(doc)
    assert [row["measured"] for row in series["metrics"][:2]] == [63.0, 0.75]
    assert series["metrics"][0]["status"] == "FAIL"
    assert series["presentation"] == "measurements"
    assert all(row["measurement_state"] == "MEASURED" for row in series["metrics"][:2])


@pytest.mark.parametrize(
    ("measured", "floor", "precision"),
    [
        (67.49, 68, 0),
        (67.5, 68, 0),
        (67.6, 68, 0),
        (67.6, 68, 2),
        (67.994, 68, 2),
        (67.999, 68, 2),
        (99.999, 100, 0),
        (99.999, 100, 2),
        (100, 100, 2),
    ],
)
def test_coverage_rounding_matches_installed_gate_without_changing_measurement(
    measured, floor, precision
):
    from coverage.results import should_fail_under

    doc = measured_document()
    doc["coverage_precision"] = precision
    doc["series"]["coverage"].update(measured=99, floor=floor)
    observations = doc["measurement_evidence"]["metrics"]
    observations[0].update(number=measured, value=f"{measured:.2f}%")
    observations[1].update(number=2.004, value="2.004%")
    mod = dashboard()
    series = mod.build_series(doc)
    assert series["metrics"][0]["status"] == (
        "FAIL" if should_fail_under(measured, floor, precision) else "PASS"
    )
    assert series["metrics"][0]["measured"] == measured
    assert series["measurements"][0]["number"] == measured
    assert series["metrics"][1]["status"] == "FAIL"  # Duplication stays unrounded.
    text = mod.markdown(doc, series)
    assert f"comparison rounded to {precision} decimal places" in text
    assert f"| Line coverage | {measured:.2f}% |" in text


@pytest.mark.parametrize("binding", ["missing", "unavailable", "contradictory"])
def test_unbound_mutation_does_not_supply_a_plot_value(binding):
    doc = measured_document()
    doc["mutation"] = {
        "sha": SHA,
        "run_id": "42",
        "profile": "light",
        "floor": 40,
        "killed": 3,
        "survived": 1,
        "total": 4,
    }
    metrics = doc["measurement_evidence"]["metrics"]
    mutation = next(row for row in metrics if row["key"] == "mutation")
    mutation.update(number=75, value="75.00%", unit="percent")
    if binding == "missing":
        metrics.remove(mutation)
    elif binding == "unavailable":
        mutation.update(state="UNAVAILABLE")
    else:
        mutation.update(number=70)
    row = dashboard().build_series(doc)["metrics"][2]
    assert row["measured"] is None
    assert row["status"] != "PASS"


@pytest.mark.parametrize("missing", [False, True])
def test_uncaptured_crap_provenance_suppresses_function_scores(missing):
    doc = measured_document()
    metrics = doc["measurement_evidence"]["metrics"]
    crap = next(row for row in metrics if row["key"] == "crap")
    if missing:
        metrics.remove(crap)
    else:
        crap.update(state="UNAVAILABLE", value="Unavailable", sources=[])
    mod = dashboard()
    text = mod.markdown(doc, mod.build_series(doc))
    assert "highest observed function scores" not in text
    assert "Service.choose" not in text
    assert "13.12" not in text


@pytest.mark.parametrize("problem", ["failed", "errors", "incomplete"])
def test_successful_job_cannot_hide_failed_or_partial_junit(problem):
    mod = dashboard()
    doc = measured_document()
    names = mod.ci_module("avo_ci_readiness", "check_ci_readiness.py").MANDATORY_JOBS
    doc["jobs"] = dict.fromkeys((*names, "ci-readiness"), "success")
    doc["test_evidence"] = {}
    doc["mutation"] = {
        "sha": SHA,
        "run_id": "42",
        "profile": "light",
        "floor": 40,
        "killed": 3,
        "survived": 1,
        "total": 4,
    }
    metrics = {row["key"]: row for row in doc["measurement_evidence"]["metrics"]}
    metrics["coverage"].update(number=80, value="80.00%")
    metrics["mutation"].update(number=75, value="75.00%", unit="percent")
    assert mod.build_series(doc)["overall"] == "PASS"

    counts = (
        None
        if problem == "incomplete"
        else {
            "total": 1,
            "passed": 0,
            "failed": int(problem == "failed"),
            "errors": int(problem == "errors"),
            "skipped": 0,
        }
    )
    reason = "Test receipt or testcase events are incomplete."
    doc["test_evidence"]["repo-unit-tests"] = {
        "state": "PARTIAL",
        "counts": counts,
        "reason": reason,
        "sources": [],
    }
    series = mod.build_series(doc)
    assert series["overall"] == ("INCOMPLETE" if counts is None else "FAIL")
    assert any("partial test evidence" in action for action in series["actions"])
    text = mod.markdown(doc, series)
    assert "| repo-unit-tests | **SUCCESS** |" in text
    assert f"PARTIAL: {reason}" in text


@pytest.mark.parametrize(
    ("direction", "threshold", "measured", "expected"),
    [
        ("minimum", 68, 67.99, "red"),
        ("minimum", 68, 68, "yellow"),
        ("minimum", 68, 75.99, "yellow"),
        ("minimum", 68, 76, "green"),
        ("maximum", 2, 2.01, "red"),
        ("maximum", 2, 2, "yellow"),
        ("maximum", 2, 1.51, "yellow"),
        ("maximum", 2, 1.5, "green"),
        ("minimum", 40, 39.99, "red"),
        ("minimum", 40, 40, "yellow"),
        ("minimum", 40, 54.99, "yellow"),
        ("minimum", 40, 55, "green"),
        ("minimum", 100, 100, "green"),
        ("minimum", 100, 99.999, "red"),
        ("maximum", 0, 0, "green"),
        ("maximum", 0, 0.001, "red"),
    ],
)
def test_threshold_bands_preserve_the_agreed_margin_boundaries(
    direction, threshold, measured, expected
):
    metric = {"direction": direction, "threshold": threshold, "measured": measured}
    assert dashboard().threshold_band(metric) == expected


@pytest.mark.parametrize("field", ["measured", "threshold"])
@pytest.mark.parametrize(
    "invalid", [None, "68", True, {}, float("nan"), float("inf"), -1, 101]
)
def test_threshold_bands_require_valid_numeric_inputs(field, invalid):
    metric = {"direction": "minimum", "threshold": 68, "measured": 76}
    metric[field] = invalid
    assert dashboard().threshold_band(metric) == "unknown"


@pytest.mark.parametrize("missing", ["measured", "threshold", "direction"])
def test_threshold_bands_do_not_invent_missing_policy_or_values(missing):
    metric = {"direction": "minimum", "threshold": 68, "measured": 76}
    del metric[missing]
    assert dashboard().threshold_band(metric) == "unknown"


def test_threshold_bands_reject_unknown_comparison_directions():
    metric = {"direction": "sideways", "threshold": 68, "measured": 76}
    assert dashboard().threshold_band(metric) == "unknown"


def test_bands_use_raw_measurements_without_changing_rounded_gate_decisions():
    doc = measured_document()
    doc["coverage_precision"] = 0
    doc["measurement_evidence"]["metrics"][0].update(number=67.6, value="67.60%")
    series = dashboard().build_series(doc)
    coverage = series["metrics"][0]
    assert coverage["measured"] == 67.6
    assert coverage["status"] == "PASS"
    assert coverage["band"] == "red"
    assert series["measurements"][0]["number"] == 67.6


@pytest.fixture
def rendered_measurements(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt

    captured = []
    close = plt.close

    def capture(figure=None):
        if hasattr(figure, "axes"):
            captured.append(figure)
        close(figure)

    monkeypatch.setattr(plt, "close", capture)

    def render(doc=None, *, old_series=False, frozen_bands=None):
        doc = measured_document() if doc is None else doc
        observations = doc["measurement_evidence"]["metrics"]
        if doc["mutation"] is None:
            doc["mutation"] = {
                "sha": SHA,
                "run_id": "42",
                "profile": "light",
                "floor": 40,
                "killed": 3999,
                "survived": 6001,
                "total": 10000,
            }
            observations[2].update(number=39.99, value="39.99%", unit="percent")
        module = dashboard()
        series = module.build_series(doc)
        if old_series:
            for metric in series["metrics"]:
                metric.pop("band", None)
        if frozen_bands is not None:
            for metric, band in zip(series["metrics"], frozen_bands, strict=True):
                metric["band"] = band
        path = tmp_path / "dashboard.png"
        module.render(series, path)
        assert len(captured) == 1
        return series, captured.pop(), path

    return render


@pytest.mark.parametrize("old_series", [False, True])
def test_active_chart_draws_margin_colors_and_preserves_series(
    rendered_measurements, old_series
):
    from matplotlib.colors import to_hex
    from PIL import Image

    doc = measured_document()
    doc["measurement_evidence"]["metrics"][0].update(number=71.25, value="71.25%")
    series, figure, path = rendered_measurements(doc, old_series=old_series)
    expected = ["#f0b400", "#18794e", "#b42318"]
    for axis, metric, color in zip(
        figure.axes, series["metrics"], expected, strict=True
    ):
        bar = next(
            patch for patch in axis.patches if patch.get_width() == metric["measured"]
        )
        assert to_hex(bar.get_facecolor()) == color
        labels = [text.get_text() for text in axis.texts]
        assert any("MEASURED" in label for label in labels)
        assert not any(label in {"PASS", "FAIL"} for label in labels)
    number = next(text for text in figure.axes[0].texts if text.get_text() == "71.25%")
    assert to_hex(number.get_color()) == "#855d00"
    for axis, margin in zip(
        figure.axes, ("Near minimum", "Clear margin", "Below minimum"), strict=True
    ):
        assert margin in [text.get_text() for text in axis.texts]
    assert series["metrics"][1]["measured"] == 0.75
    if not old_series:
        assert [metric["band"] for metric in series["metrics"]] == [
            "yellow",
            "green",
            "red",
        ]
    with Image.open(path) as image:
        assert json.loads(image.info["Description"]) == series


def test_active_chart_keeps_threshold_marks_and_labels_in_measurement_view(
    rendered_measurements,
):
    from matplotlib.collections import LineCollection

    series, figure, _ = rendered_measurements()
    assert series["presentation"] == "measurements"
    for axis, metric in zip(figure.axes, series["metrics"], strict=True):
        segments = [
            segment
            for collection in axis.collections
            if isinstance(collection, LineCollection)
            for segment in collection.get_segments()
        ]
        assert any(
            segment[:, 0].tolist() == [metric["threshold"], metric["threshold"]]
            and segment[0, 1] != segment[1, 1]
            for segment in segments
        )
        direction = "Minimum" if metric["direction"] == "minimum" else "Maximum"
        assert any(
            f"{direction} {metric['threshold']:g}%" in text.get_text()
            for text in axis.texts
        )


def test_chart_uses_frozen_bands_instead_of_gate_status(rendered_measurements):
    from matplotlib.colors import to_hex

    _, figure, _ = rendered_measurements(frozen_bands=("green", "yellow", "red"))
    assert [to_hex(axis.patches[-1].get_facecolor()) for axis in figure.axes] == [
        "#18794e",
        "#f0b400",
        "#b42318",
    ]


@pytest.mark.parametrize("invalid", [None, float("nan"), True, -1, 101])
def test_unavailable_measurements_stay_neutral_without_a_measured_bar(
    rendered_measurements, invalid
):
    from matplotlib.colors import to_hex

    doc = measured_document()
    doc["measurement_evidence"]["metrics"][0]["number"] = invalid
    series, figure, _ = rendered_measurements(doc)
    assert series["metrics"][0]["measured"] is None
    assert series["metrics"][0]["band"] == "unknown"
    assert len(figure.axes[0].patches) == 1
    unavailable = [
        text for text in figure.axes[0].texts if text.get_text() == "Unavailable"
    ]
    assert unavailable
    assert all(to_hex(text.get_color()) == "#667085" for text in unavailable)


@pytest.mark.parametrize("invalid", [None, "68", True, float("nan"), -1, 101])
def test_unknown_thresholds_preserve_measurements_without_quality_colors(
    rendered_measurements, invalid
):
    from matplotlib.colors import to_hex

    doc = measured_document()
    doc["series"]["coverage"]["floor"] = invalid
    series, figure, _ = rendered_measurements(doc)
    metric = series["metrics"][0]
    assert metric["measured"] == 63.0
    assert metric["threshold"] is None
    assert metric["band"] == "unknown"
    assert to_hex(figure.axes[0].patches[-1].get_facecolor()) == "#667085"
    assert not figure.axes[0].collections
    assert any(
        text.get_text() == "Threshold unavailable" for text in figure.axes[0].texts
    )
