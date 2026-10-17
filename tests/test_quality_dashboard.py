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


def test_report_context_distinguishes_head_tested_revision_and_attempt():
    doc = document(
        reporting={
            "schema": 1,
            "mode": "ci",
            "pr_number": 100,
            "head_sha": "b" * 40,
            "base_sha": "c" * 40,
            "run_attempt": 2,
        }
    )
    mod = dashboard()
    text = mod.markdown(doc, mod.build_series(doc))
    assert "PR head" in text and "b" * 40 in text
    assert "Tested revision" in text and SHA in text
    assert "Attempt: 2" in text


def test_oversized_diagnostics_do_not_clip_actions_or_cut_table_rows():
    doc = document()
    doc["gates"][0]["metric"] = "Inspect coverage."
    doc["gates"][0]["status"] = "FAIL"
    doc["measurement_evidence"] = {
        "schema": 1,
        "metrics": [
            {
                "key": "deadcode",
                "title": "Dead code",
                "state": "MEASURED",
                "number": None,
                "value": "2 findings",
                "scope": "src/avo",
                "basis": "large detail " * 10000,
                "sources": [],
            }
        ],
        "gates": {},
        "diagnostics": {},
    }
    mod = dashboard()
    text = mod.markdown(doc, mod.build_series(doc))
    assert len(text) <= 48000
    assert "Inspect coverage." in text
    assert "complete" in text.lower() and "excerpt" in text.lower()
    assert text.count("<details>") == text.count("</details>")


def test_budget_never_replaces_a_long_required_action_with_a_generic_excerpt():
    mod = dashboard()
    action = "- Failed coverage: " + "required-fix " * 300
    lines = ["## AVO quality", "**Required action**", action] + [
        "diagnostic " + "x" * 89
    ] * 460
    try:
        text = mod.bounded_report(lines)
    except ValueError:
        return  # Fatal writer fallback is explicit failure, never a lost action.
    assert action in text


def test_source_labels_and_recorded_reasons_cannot_inject_markdown_links():
    text = dashboard().safe_text(
        "test [safe](https://untrusted.invalid) `fake PASS` | <b>"
    )
    assert "[safe](" not in text
    assert "`fake PASS`" not in text
    assert "<b>" not in text


@pytest.mark.parametrize("mode", ["fixture", "local-preview"])
def test_preview_diagnostics_never_claim_committed_source_links(mode):
    doc = document(repository="owner/avo", reporting={"schema": 1, "mode": mode})
    assert "https://" not in dashboard().source_link(doc, "src/avo/sample.py", 1)


def test_diagnostic_source_links_validate_identity_and_encode_path():
    mod = dashboard()
    doc = document(repository="owner/avo")  # Supported historical context.
    assert "%29" in mod.source_link(doc, "src/avo/a)b.py", 1)
    for repository in ("owner/..", "owner/repo)bad", "../avo"):
        assert "https://" not in mod.source_link(
            document(repository=repository), "src/avo/sample.py", 1
        )


def test_unavailable_synopsis_does_not_interrupt_primary_measurement_table():
    doc = measured_document()
    doc["measurement_evidence"]["metrics"][-1]["state"] = "UNAVAILABLE"
    mod = dashboard()
    text = mod.markdown(doc, mod.build_series(doc))
    table = text.split("| Metric | Measured | Scope | Evidence |", 1)[1].split(
        "\n\n", 1
    )[0]
    assert "Coverage" in table or "coverage" in table
    assert "Duplication" in table
    assert "Unavailable evidence:" not in table


def test_definition_reference_is_traceable_and_conflicts_are_disclosed():
    doc = measured_document()
    doc["reporting"] = {"schema": 1, "mode": "ci"}
    mod = dashboard()
    definitions = mod.ci_module(
        "avo_ci_quality_measurements", "quality_measurements.py"
    )
    definitions.freeze_definitions(doc)
    block = doc["metric_definitions"]
    text = mod.markdown(doc, mod.build_series(doc))
    assert block["catalog_sha256"] in text and block["policy_sha256"] in text
    assert f"blob/{SHA}/tests/fixtures/quality_metrics/definitions.json" in text
    before = mod.build_series(doc)["overall"]
    block["reference"]["sha"] = "b" * 40
    text = mod.markdown(doc, mod.build_series(doc))
    assert "Metric-definition identity unavailable" in text
    assert "another measured revision" in text
    assert mod.build_series(doc)["overall"] == before


def test_generated_ci_entrypoint_has_canonical_repository_and_valid_context(
    tmp_path, monkeypatch
):
    from scripts.ci import gen_kpi_charts as charts
    from scripts.ci.quality_measurements import validate_reporting_context
    from scripts.ci.write_quality_pr_report import GATES

    (tmp_path / "pyproject.toml").write_text("[tool.coverage.report]\nfail_under=68\n")
    (tmp_path / ".jscpd.json").write_text('{"threshold":2}')
    policy = tmp_path / "scripts/ci"
    policy.mkdir(parents=True)
    (policy / "mutation-config.json").write_text('{"light":{"min_killed_percent":40}}')
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/avo")
    _text, doc = charts.generate_dashboard(
        {key: "success" for key, _ in GATES},
        coverage_json=tmp_path / "coverage.json",
        floor=68,
        root=tmp_path,
        out_dir=tmp_path / "charts",
    )
    assert doc.get("repository") == "owner/avo"
    assert doc.get("run_url") == "https://github.com/owner/avo/actions/runs/42"
    assert validate_reporting_context(doc) is None


def support_document():
    doc = document(reporting={"schema": 1, "mode": "fixture"})
    node = {
        "module": "avo.sample",
        "kind": "file",
        "path": "src/avo/sample.py",
        "sha256": "d" * 64,
        "ca": 0,
        "ce": 0,
        "instability": None,
    }
    function = {
        "id": "avo.sample.work@src/avo/sample.py:1",
        "module": "avo.sample",
        "qualname": "work",
        "path": node["path"],
        "line": 1,
        "end_line": 3,
        "source_sha256": node["sha256"],
        "complexity": 6,
        "function_coverage": {
            "status": "MEASURED",
            "covered_lines": 0,
            "num_statements": 3,
            "percent": 0,
        },
        "crap": {"status": "MEASURED", "value": 42, "reason": "fixed example"},
    }
    doc["measurement_evidence"] = {
        "schema": 1,
        "metrics": [],
        "gates": {},
        "diagnostics": {},
        "supporting": {
            "schema": 1,
            "source_fingerprint": "e" * 64,
            "sources": [],
            "coupling": {
                "state": "MEASURED",
                "modules": [node],
                "edges": [],
                "node_count": 1,
                "edge_count": 0,
                "topology_sha256": "f" * 64,
            },
            "functions": {
                "state": "MEASURED",
                "reason": "Fixed example",
                "records": [function],
                "observed_functions": 1,
                "measured_crap_functions": 1,
                "unmeasured_observed_functions": 0,
                "source_errors": [],
                "total_population_known": True,
            },
        },
    }
    return doc


def test_coupling_text_uses_its_frozen_axis_interpretation():
    mod = dashboard()
    doc = support_document()
    mod.build_supporting(doc)
    text = mod.markdown(doc, mod.build_series(doc))
    assert "piecewise log2(1 + count) around raw median" in text
    assert "halves use independent scales" in text
    assert "lower numeric range is empty" in text
    # A historical frozen series must not acquire today's display description.
    doc["series"]["coupling_files"]["axes"] = {"transform": "log2(1 + count)"}
    text = mod.markdown(doc, mod.build_series(doc))
    assert "Spacing: log2(1 + count)" in text
    assert "halves use independent scales" not in text


def test_supporting_views_share_text_indexes_and_survive_one_image_failure(
    tmp_path, monkeypatch
):
    mod = dashboard()
    doc = support_document()
    mod.build_supporting(doc)
    coupling = mod.ci_module("avo_ci_coupling_dashboard", "coupling_dashboard.py")

    def fail(*_args):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(coupling, "render_coupling", fail)
    mod.render_supporting(doc, tmp_path)
    text = mod.markdown(doc, mod.build_series(doc))
    assert (tmp_path / "coupling/coupling-index.md").is_file()
    assert (tmp_path / "hotspots/hotspots.md").is_file()
    assert doc["coupling_image_error"]
    assert not doc.get("hotspots_image_error")
    assert "G01" in text and "F001" in text and "src/avo/sample.py" in text
    assert "U0001" in text and "42" in text
    assert "kpi-chart:hotspots.png" in text
    assert "kpi-detail:coupling-index.md" in text
    assert "image unavailable" in text.lower()


def test_findings_and_exception_reasons_keep_units_and_missing_context():
    doc = measured_document()
    doc["measurement_evidence"]["diagnostics"]["exception_summaries"] = [
        {
            "tool": "deadcode",
            "configured_entries": 150,
            "matched_findings": 2,
            "unique_affected": 1,
            "stale_entries": None,
            "unwaived_findings": 0,
            "non_additive": True,
            "members": [
                {
                    "path": "src/avo/sample.py",
                    "name": "sample",
                    "line": 1,
                    "reason": None,
                    "disposition": "allowlisted",
                }
            ],
        }
    ]
    mod = dashboard()
    text = mod.markdown(doc, mod.build_series(doc))
    assert "configured entries" in text and "matched findings" in text
    assert "unique affected" in text and "non-additive" in text
    assert "Rationale unavailable" in text and "stale: Unavailable" in text


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
    assert "Dashboard image unavailable; current measurements remain in text." in text


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


@pytest.mark.parametrize("outcome", ["skipped", "failed"])
def test_execution_reasons_follow_the_complete_required_job_table(outcome):
    doc = measured_document()
    doc["jobs"]["software-quality"] = "success"
    doc["test_evidence"]["repo-unit-tests"]["cases"] = [
        {
            "suite": "unit",
            "classname": "TestSource",
            "name": "test_case",
            "outcome": outcome,
            "reason": "Recorded early-job reason",
        }
    ]
    mod = dashboard()
    text = mod.markdown(doc, mod.build_series(doc))
    execution = text.split("<summary>Execution results</summary>", 1)[1].split(
        "</details>", 1
    )[0]
    table = execution.split("| Required job |", 1)[1].split("\n\n", 1)[0]
    for job in doc["jobs"]:
        assert f"| {job} | **SUCCESS** |" in table
    assert execution.index("| software-quality |") < execution.index(
        "Recorded skip/failure reasons:"
    )
    assert "Recorded early-job reason" in execution


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
