"""Reviewed meaning and fixed behavior; verification never writes expectations."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
from pathlib import Path

import pytest
from coverage import Coverage
from scripts.ci import (
    avo_dep_graph,
    check_mutation,
    coupling_dashboard,
    measure_code_risk,
    quality_dashboard,
    quality_hotspots,
    quality_measurements,
    test_execution_evidence,
    write_quality_pr_report,
)
from scripts.ci import (
    quality_metric_definitions as definitions,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/quality_metrics"
SHA = "a" * 40


def read(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def compare(expected, actual, label):
    before = json.dumps(expected, sort_keys=True, indent=2).splitlines()
    after = json.dumps(actual, sort_keys=True, indent=2).splitlines()
    assert expected == actual, (
        label
        + "\n"
        + "\n".join(
            difflib.unified_diff(before, after, fromfile="expected", tofile="actual")
        )
    )


def compare_primary(expected, actual, label):
    if expected["number"] is None:
        compare(expected, actual, label)
        return
    assert actual["number"] == pytest.approx(expected["number"], abs=1e-10, rel=0), (
        f"{label}.number: expected {expected['number']}, actual {actual['number']}"
    )
    compare(
        {key: value for key, value in expected.items() if key != "number"},
        {key: value for key, value in actual.items() if key != "number"},
        label,
    )


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def document():
    return {
        "sha": SHA,
        "run_id": "42",
        "floor": 68.0,
        "coverage_precision": 0,
        "mutation_policy": {"profile": "light", "floor": 40.0},
        "series": {"coverage": {"floor": 68.0}, "duplication": {"ceiling": 2.0}},
        "gates": [],
    }


def catalog_projection(block):
    return {
        "schema": block["schema"],
        "entries": [
            {key: value for key, value in entry.items() if key != "sha256"}
            for entry in block["entries"]
        ],
    }


def test_reviewed_catalog_covers_every_published_metric_and_diagnostic():
    expected = read("definitions.json")
    actual = catalog_projection(definitions.build_definitions(document()))
    required = set(quality_measurements.KEYS) | {
        "coupling_files",
        "execution_events",
        "mutation_scopes",
        "gate_decisions",
    }
    assert {entry["id"] for entry in actual["entries"]} == required
    for expected_entry, actual_entry in zip(
        expected["entries"], actual["entries"], strict=True
    ):
        compare(expected_entry, actual_entry, f"definition:{expected_entry['id']}")
    compare(expected, actual, "metric catalog")
    covered = (
        {case["metric"] for case in read("cases/primary.json")}
        | {
            "mutation",
            "complexity",
            "crap",
            "coupling",
            "coupling_files",
            "execution_events",
            "mutation_scopes",
            "gate_decisions",
        }
        | set(read("cases/counts.json")["expected"])
    )
    assert covered == required, (
        "Every catalog ID requires a fixed production-path case."
    )


def test_resolved_policy_matches_independently_reviewed_baseline():
    config = read("policy.json")
    mutation = json.loads((ROOT / "scripts/ci/mutation-config.json").read_text())
    actual = {
        "schema": 1,
        "coverage_floor": write_quality_pr_report.coverage_floor_from_pyproject(
            ROOT / "pyproject.toml"
        ),
        "coverage_precision": Coverage(
            config_file=str(ROOT / "pyproject.toml")
        ).config.precision,
        "duplication_ceiling": write_quality_pr_report.duplication_ceiling(ROOT),
        "mutation_profiles": {
            profile: values["min_killed_percent"]
            for profile, values in mutation.items()
        },
    }
    compare(config, actual, "effective policy")


def reporting_document():
    doc = document()
    doc.update(reporting={"schema": 1, "mode": "fixture"}, jobs={})
    doc["measurement_evidence"] = {"schema": 1, "metrics": [], "gates": {}}
    return doc


@pytest.mark.parametrize(
    "case", read("cases/reporting-views.json")["mutation_scopes"], ids=lambda c: c["id"]
)
def test_reviewed_scope_behavior_cases_use_the_production_view(case):
    from scripts.ci import mutation_scopes, quality_mutation_dashboard

    doc = reporting_document()
    doc["mutation"] = {
        "sha": SHA,
        "run_id": "42",
        "profile": "light",
        "floor": 40,
        "counts": case["counts"],
    }
    doc["measurement_evidence"]["metrics"] = [
        {
            "key": "mutation",
            "state": case["state"],
            "number": case["score"],
            "unit": "percent",
            "sources": [
                {
                    "artifact": "mutation-reports-light",
                    "path": "mutation-metrics.json",
                    "sha256": "b" * 64,
                }
            ],
        }
    ]
    normalized = check_mutation.normalize_mutation_counts(case["counts"])
    normalized["unaccounted"] = normalized["total"] - sum(
        normalized[key] for key in check_mutation.MUTANT_STATUSES
    )
    row = mutation_scopes._measurement(normalized)
    compare(
        {key: case[key] for key in ("state", "score", "complete", "unresolved")},
        {key: row[key] for key in ("state", "score", "complete", "unresolved")},
        f"mutation_scopes:{case['id']}:derived-outcomes",
    )
    row.update(path="src/avo/a.py", reason=case["id"], source_sha256="c" * 64)
    refs = [
        {
            "artifact": "mutation-reports-light",
            "path": "mutation-scopes.json",
            "sha256": "e" * 64,
        }
    ]
    doc["measurement_evidence"]["mutation_scopes"] = {
        "schema": 1,
        "state": case["state"],
        "reason": case["id"],
        "profile": "light",
        "threshold_scope": "aggregate",
        "sources": refs,
        "source_fingerprint": quality_mutation_dashboard.fingerprint(refs),
        "scopes": [row],
    }
    actual = quality_mutation_dashboard.build_mutation_series(doc)["scopes"][0]
    compare(
        case["expected"],
        {key: actual[key] for key in case["expected"]},
        f"mutation_scopes:{case['id']}",
    )


@pytest.mark.parametrize(
    "case", read("cases/reporting-views.json")["gate_decisions"], ids=lambda c: c["id"]
)
def test_reviewed_gate_decision_cases_use_the_production_view(case):
    from scripts.ci import quality_gate_decisions

    doc = reporting_document()
    doc["gates"] = [
        {
            "key": "lint",
            "title": "Lint",
            "status": case["reported"],
            "checks": "Existing lint policy",
        }
    ]
    doc["measurement_evidence"]["gates"]["lint"] = {
        "verified": case["verified"],
        "reason": "Fixed captured-proof case",
        "receipt": {"status": case["receipt_status"], "exit_code": case["exit_code"]},
        "sources": [
            {
                "artifact": "quality-evidence",
                "path": "gates/lint/gate.json",
                "sha256": "d" * 64,
            }
        ],
    }
    actual = next(
        row
        for row in quality_gate_decisions.build_gate_series(doc)["rows"]
        if row["key"] == "lint"
    )
    compare(
        case["expected"],
        {key: actual[key] for key in case["expected"]},
        f"gate_decisions:{case['id']}",
    )


def test_runtime_policy_uses_only_frozen_applicable_fields():
    doc = document()
    doc.update(floor=61, coverage_precision=2)
    doc["series"]["duplication"]["ceiling"] = 3
    doc["mutation_policy"] = {"profile": "full", "floor": 51}
    block = definitions.build_definitions(doc)
    compare(
        {
            "coverage_floor": 61.0,
            "coverage_precision": 2,
            "duplication_ceiling": 3.0,
            "mutation": {"profile": "full", "floor": 51.0},
        },
        block["policy"],
        "frozen policy",
    )
    assert block["policy_sha256"] == digest(block["policy"])
    assert block["reference"] == {
        "path": "tests/fixtures/quality_metrics/definitions.json",
        "sha": SHA,
    }
    assert definitions.validate_definitions(block) is None


def test_unknown_policy_is_unavailable_not_current_configuration():
    block = definitions.build_definitions({"sha": SHA})
    assert block["policy"] == {
        "coverage_floor": None,
        "coverage_precision": None,
        "duplication_ceiling": None,
        "mutation": {"profile": None, "floor": None},
    }
    assert definitions.validate_definitions(block) is None


@pytest.mark.parametrize(
    "invalid", [True, [], "68", -1, 101, float("nan"), float("inf")]
)
def test_invalid_frozen_policy_values_cannot_become_numbers(invalid):
    doc = document()
    doc.update(floor=invalid, coverage_precision=True)
    doc["series"]["duplication"]["ceiling"] = invalid
    doc["mutation_policy"] = {"profile": [], "floor": invalid}
    block = definitions.build_definitions(doc)
    assert block["policy"] == {
        "coverage_floor": None,
        "coverage_precision": None,
        "duplication_ceiling": None,
        "mutation": {"profile": None, "floor": None},
    }
    assert definitions.validate_definitions(block) is None


@pytest.mark.parametrize(
    "damage",
    ["entry", "catalog", "policy", "reference", "revision", "duplicate", "order"],
)
def test_offline_validation_rejects_inconsistent_metadata(damage):
    block = definitions.build_definitions(document())
    if damage == "entry":
        block["entries"][0]["unit"] = "percent"
    elif damage == "catalog":
        block["catalog_sha256"] = "b" * 64
    elif damage == "policy":
        block["policy"]["coverage_floor"] = 0
    elif damage == "reference":
        block["reference"]["path"] = "../secrets"
    elif damage == "revision":
        block["entries"][0]["revision"] = True
    elif damage == "duplicate":
        block["entries"].append(copy.deepcopy(block["entries"][0]))
    else:
        block["entries"].reverse()
    assert definitions.validate_definitions(block)


def test_historical_metadata_is_validated_without_current_catalog_reinterpretation():
    block = definitions.build_definitions(document())
    entry = block["entries"][0]
    entry.update(revision=2, calculation="An older reviewed direct count definition.")
    entry["sha256"] = digest(
        {key: value for key, value in entry.items() if key != "sha256"}
    )
    block["catalog_sha256"] = digest(catalog_projection(block))
    assert definitions.validate_definitions(block) is None
    assert block["entries"][0]["revision"] == 2


def _captured_outputs(monkeypatch, outputs, *, architecture=False):
    proofs = {
        key: {
            "verified": key != "architecture" or architecture,
            "sources": [],
            "receipt": {"status": "PASS"},
        }
        for key in (
            "coverage",
            "duplication",
            "deadcode",
            "deps",
            "architecture",
            "tree",
        )
    }
    monkeypatch.setattr(quality_measurements, "gate_evidence", lambda *args: proofs)
    monkeypatch.setattr(
        quality_measurements,
        "output",
        lambda _proofs, _gate, name, _directory: (copy.deepcopy(outputs.get(name)), []),
    )


def run_primary(case, monkeypatch, tmp_path):
    key = case["metric"]
    doc = document()
    doc["gates"] = [{"key": key, "status": "PASS"}]
    doc["coverage_precision"] = case.get("precision", 0)
    doc["series"][key] = {
        "floor" if key == "coverage" else "ceiling": case["threshold"]
    }
    if key == "coverage":
        outputs = {"coverage.json": {"totals": case["counts"]}}
    else:
        outputs = {
            "jscpd/jscpd-report.json": {
                "statistics": {"total": case["counts"]},
                "duplicates": [],
            }
        }
    _captured_outputs(monkeypatch, outputs)
    evidence = quality_measurements.collect(doc, tmp_path)
    doc["measurement_evidence"] = evidence
    observation = next(row for row in evidence["metrics"] if row["key"] == key)
    metric = quality_dashboard.measured_metric(
        doc, key, key.title(), "minimum" if key == "coverage" else "maximum", key
    )
    return {
        "state": observation["state"],
        "number": observation["number"],
        "gate_status": metric["status"],
        "band": quality_dashboard.threshold_band(metric),
    }


@pytest.mark.parametrize(
    "case", read("cases/primary.json"), ids=lambda case: case["id"]
)
def test_fixed_primary_inputs_use_actual_normalization_and_interpretation(
    case, monkeypatch, tmp_path
):
    compare_primary(
        case["expected"], run_primary(case, monkeypatch, tmp_path), case["id"]
    )


def test_fixed_mutation_outcomes_and_profile_binding():
    fixture = read("cases/mutation.json")
    for case in fixture["cases"]:
        actual = check_mutation.mutation_evaluation(
            case["counts"], min_killed_percent=40
        )
        compare(
            case["expected"], {key: actual[key] for key in case["expected"]}, case["id"]
        )
    unresolved = fixture["unresolved_categories"]
    assert set(unresolved) == set(check_mutation.MUTANT_STATUSES) - {
        "killed",
        "survived",
    }
    for category in unresolved:
        counts = {"killed": 2, "survived": 3, "total": 6, category: 1}
        actual = check_mutation.mutation_evaluation(counts, min_killed_percent=40)
        expected = fixture["unresolved_expected"]
        compare(
            expected, {key: actual[key] for key in expected}, f"mutation:{category}"
        )
    doc = document()
    doc["mutation"] = {
        "sha": SHA,
        "run_id": "42",
        "profile": "full",
        "floor": 40,
        "counts": {"killed": 5, "survived": 0, "total": 5},
    }
    metric = quality_dashboard.mutation_metric(doc)
    compare(
        fixture["profile_mismatch_expected"],
        {key: metric[key] for key in fixture["profile_mismatch_expected"]},
        "mutation:profile",
    )


def test_real_cc_crap_and_partial_hotspot_fixed_cases(tmp_path):
    fixture = read("cases/code-risk.json")
    for case in fixture["formula_cases"]:
        actual = measure_code_risk.crap_score(case["complexity"], case["coverage"])
        assert actual == case["expected"], f"crap:{case}"
    package = tmp_path / "src/avo"
    package.mkdir(parents=True)
    path = package / "logic.py"
    path.write_text(
        fixture["source"]
        + "\ndef other(value):\n    if value:\n        return 1\n    return 0\n"
    )
    (package / "broken.py").write_text("def broken(:")
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "meta": {"format": 3},
                "files": {
                    "src/avo/logic.py": {
                        "functions": {"choose": fixture["function_region"]}
                    }
                },
            }
        )
    )
    risk = measure_code_risk.build_report(
        root=tmp_path,
        coverage_path=coverage,
        sha=SHA,
        run_id="42",
        recorded_at="2026-10-16T00:00:00Z",
        test_outcome="success",
    )
    row = risk["functions"][0]
    expected = fixture["expected"]
    assert row["complexity"] == expected["complexity"]
    assert row["function_coverage"]["percent"] == pytest.approx(
        expected["coverage"], abs=1e-10, rel=0
    )
    assert row["crap"]["value"] == pytest.approx(expected["crap"], abs=1e-10, rel=0)
    sources = {
        item["path"]: item["sha256"] for item in risk["provenance"]["sources"]["files"]
    }
    records = [
        {**item, "source_sha256": sources[item["path"]]} for item in risk["functions"]
    ]
    doc = document()
    doc["reporting"] = {"schema": 1, "mode": "fixture"}
    doc["measurement_evidence"] = {
        "supporting": {
            "schema": 1,
            "functions": {
                "state": "PARTIAL",
                "records": records,
                "observed_functions": 2,
                "measured_crap_functions": 1,
                "unmeasured_observed_functions": 1,
                "total_population_known": False,
                "source_errors": risk["source_errors"],
            },
        }
    }
    series = quality_hotspots.build_hotspot_series(doc)
    compare(
        fixture["support_expected"],
        {
            "complexity_ids": series["rankings"]["complexity"]["ids"],
            "crap_ids": series["rankings"]["crap"]["ids"],
            "observed": series["population"]["observed_functions"],
            "measured": series["population"]["measured_crap_functions"],
            "unmeasured": series["population"]["unmeasured_observed_functions"],
            "known": series["population"]["total_population_known"],
        },
        "complexity/crap:rankings",
    )


def test_real_graph_and_indexed_positions_match_reviewed_fixture(tmp_path):
    fixture = read("cases/graph.json")
    source = tmp_path / "src/avo"
    for name, text in fixture["files"].items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    nodes, edges = avo_dep_graph.collect_edges(source, granularity="module")
    actual = {
        "nodes": sorted(nodes),
        "edges": [list(edge) for edge in sorted(edges)],
        "degrees": {
            node: [
                sum(target == node for _origin, target in edges),
                sum(origin == node for origin, _target in edges),
            ]
            for node in sorted(nodes)
        },
    }
    compare(fixture["expected"], actual, "coupling_files:graph")
    nodes, edges = avo_dep_graph.collect_edges(source)
    compare(
        fixture["package_expected"],
        {"nodes": sorted(nodes), "edges": [list(edge) for edge in sorted(edges)]},
        "coupling:package",
    )
    graph = measure_code_risk._module_coupling(
        source, measure_code_risk.source_manifest(tmp_path)
    )
    doc = document()
    doc["reporting"] = {"schema": 1, "mode": "fixture"}
    doc["measurement_evidence"] = {
        "supporting": {"schema": 1, "coupling": {**graph, "state": graph["status"]}}
    }
    quality_measurements.freeze_definitions(doc)
    series = coupling_dashboard.build_coupling_series(doc)
    assert series["definition_identity"]["catalog_sha256"] == digest(
        read("definitions.json")
    )
    assert (
        next(
            entry["revision"]
            for entry in doc["metric_definitions"]["entries"]
            if entry["id"] == "coupling_files"
        )
        == 2
    )
    compare(
        fixture["support_expected"],
        {
            "ce_median": series["references"]["ce"],
            "ca_median": series["references"]["ca"],
            "file_count": series["file_count"],
            "namespace_count": series["namespace_count"],
            "axes": series["axes"],
            "groups": [
                {key: group[key] for key in ("id", "ce", "ca", "file_ids")}
                for group in series["groups"]
            ],
        },
        "coupling_files:positions",
    )


@pytest.mark.parametrize(
    "case", read("cases/graph.json")["axis_cases"], ids=lambda case: case["id"]
)
def test_file_coupling_axis_spacing_matches_reviewed_fixed_cases(case):
    actual = coupling_dashboard.axis_position(
        case["count"], case["reference"], case["maximum"]
    )
    assert actual == pytest.approx(case["expected"], abs=1e-12, rel=0), (
        f"coupling_files.axis:{case['id']}: expected {case['expected']}, actual {actual}"
    )


def test_fixed_coupling_axis_detects_behavior_drift_without_catalog_changes(
    monkeypatch,
):
    original = definitions.build_definitions(document())
    case = next(
        row
        for row in read("cases/graph.json")["axis_cases"]
        if row["id"] == "lower-log-midpoint"
    )
    monkeypatch.setattr(
        coupling_dashboard,
        "axis_position",
        lambda count, _reference, maximum: count / maximum,
        raising=False,
    )
    with pytest.raises(AssertionError, match="coupling_files.axis"):
        compare(
            case["expected"],
            coupling_dashboard.axis_position(
                case["count"], case["reference"], case["maximum"]
            ),
            "coupling_files.axis:" + case["id"],
        )
    assert definitions.build_definitions(document()) == original


def test_fixed_execution_and_findings_use_observed_units(monkeypatch, tmp_path):
    fixture = read("cases/counts.json")
    compare(
        fixture["execution_expected"],
        test_execution_evidence._counts(fixture["junit"].encode()),
        "execution_events",
    )
    outputs = {
        name: {**payload, "sha": SHA, "run_id": "42"}
        for name, payload in fixture["outputs"].items()
    }
    _captured_outputs(monkeypatch, outputs, architecture=True)
    log = tmp_path / "gates/architecture/gate.log"
    log.parent.mkdir(parents=True)
    log.write_text(fixture["architecture_log"])
    doc = document()
    evidence = quality_measurements.collect(doc, tmp_path)
    actual = {
        row["key"]: {"value": row["value"], "state": row["state"]}
        for row in evidence["metrics"]
        if row["key"] in fixture["expected"]
    }
    compare(fixture["expected"], actual, "findings/proposals/scheduled-branches")


def test_read_only_baselines_detect_behavior_drift_and_ignore_declared_volatility(
    monkeypatch, tmp_path
):
    before = {path: path.read_bytes() for path in FIXTURES.rglob("*") if path.is_file()}
    doc = document()
    original = definitions.build_definitions(doc)
    doc.update(
        run_id="99",
        recorded_at="2027-01-01T00:00:00Z",
        run_url="https://example.invalid/other",
    )
    changed = definitions.build_definitions(doc)
    assert original == changed
    case = read("cases/primary.json")[0]
    compare_primary(
        case["expected"], run_primary(case, monkeypatch, tmp_path), case["id"]
    )
    monkeypatch.setattr(quality_dashboard, "threshold_band", lambda _metric: "green")
    with pytest.raises(AssertionError, match="coverage-raw-rounding"):
        compare_primary(
            case["expected"], run_primary(case, monkeypatch, tmp_path), case["id"]
        )
    assert before == {
        path: path.read_bytes() for path in FIXTURES.rglob("*") if path.is_file()
    }


def test_missing_definition_and_semantic_policy_changes_have_readable_differences():
    expected = read("definitions.json")
    actual = catalog_projection(definitions.build_definitions(document()))
    actual["entries"].pop()
    with pytest.raises(AssertionError, match="metric catalog"):
        compare(expected, actual, "metric catalog")
    actual = copy.deepcopy(expected)
    actual["entries"][0]["calculation"] = "Changed counting rule."
    with pytest.raises(AssertionError, match="calculation"):
        compare(expected, actual, "architecture definition")
    policy = read("policy.json")
    changed = {**policy, "coverage_precision": 2}
    with pytest.raises(AssertionError, match="coverage_precision"):
        compare(policy, changed, "coverage policy")


def test_fixed_math_detects_behavior_drift_without_description_changes(monkeypatch):
    original = definitions.build_definitions(document())
    case = read("cases/code-risk.json")["formula_cases"][0]
    monkeypatch.setattr(measure_code_risk, "crap_score", lambda cc, _coverage: cc)
    with pytest.raises(AssertionError, match="crap.calculation"):
        compare(
            {"score": case["expected"]},
            {
                "score": measure_code_risk.crap_score(
                    case["complexity"], case["coverage"]
                )
            },
            "crap.calculation",
        )
    assert definitions.build_definitions(document()) == original


def test_fixed_events_detect_counting_drift(monkeypatch):
    fixture = read("cases/counts.json")
    original = test_execution_evidence._counts

    def incorrect_unique_count(raw):
        counts = original(raw)
        return {**counts, "passed": counts["passed"] - 1, "total": counts["total"] - 1}

    monkeypatch.setattr(test_execution_evidence, "_counts", incorrect_unique_count)
    with pytest.raises(AssertionError, match="execution_events.counting"):
        compare(
            fixture["execution_expected"],
            test_execution_evidence._counts(fixture["junit"].encode()),
            "execution_events.counting",
        )


def test_fixed_primary_detects_rounding_drift(monkeypatch, tmp_path):
    case = read("cases/primary.json")[0]
    monkeypatch.setattr(
        quality_dashboard, "round", lambda value, _precision: value, raising=False
    )
    with pytest.raises(AssertionError, match="gate_status"):
        compare_primary(
            case["expected"], run_primary(case, monkeypatch, tmp_path), case["id"]
        )


def test_fixed_mutation_detects_incomplete_state_drift(monkeypatch):
    fixture = read("cases/mutation.json")
    original = check_mutation.mutation_evaluation

    def incorrect_complete(stats, **kwargs):
        result = original(stats, **kwargs)
        return {**result, "complete": True, "score": 40.0}

    monkeypatch.setattr(check_mutation, "mutation_evaluation", incorrect_complete)
    actual = check_mutation.mutation_evaluation(
        {"killed": 2, "survived": 3, "total": 6, "timeout": 1}, min_killed_percent=40
    )
    expected = fixture["unresolved_expected"]
    with pytest.raises(AssertionError, match="mutation.incomplete"):
        compare(expected, {key: actual[key] for key in expected}, "mutation.incomplete")
