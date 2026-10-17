"""Additive mutation/gate views preserve proof boundaries and existing decisions."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest
from scripts.ci import (
    check_ci_readiness,
    quality_dashboard,
    quality_measurements,
    write_unified_quality_report,
)
from scripts.ci.write_quality_pr_report import GATES

SHA = "a" * 40


def document():
    counts = {"killed": 6, "survived": 4, "total": 10}
    return {
        "schema": 2,
        "sha": SHA,
        "run_id": "42",
        "reporting": {"schema": 1, "mode": "local-preview"},
        "floor": 68,
        "coverage_precision": 0,
        "overall": "PASS",
        "mutation_policy": {"profile": "light", "floor": 40},
        "mutation": {
            "sha": SHA,
            "run_id": "42",
            "profile": "light",
            "floor": 40,
            "counts": counts,
        },
        "gates": [
            {"key": key, "title": title, "status": "PASS", "checks": "Existing policy"}
            for key, title in GATES
        ],
        "series": {"coverage": {"floor": 68}, "duplication": {"ceiling": 2}},
        "jobs": {
            key: "success"
            for key in (*check_ci_readiness.MANDATORY_JOBS, "ci-readiness")
        },
        "measurement_evidence": {
            "schema": 1,
            "metrics": [
                {
                    "key": "mutation",
                    "title": "Mutation efficacy",
                    "state": "MEASURED",
                    "number": 60.0,
                    "unit": "percent",
                    "value": "60.00%",
                    "basis": "6 killed; 4 survived; 0 unresolved",
                    "scope": "light profile",
                    "sources": [
                        {
                            "artifact": "mutation-reports-light",
                            "path": "mutation-metrics.json",
                            "sha256": "b" * 64,
                        }
                    ],
                }
            ],
            "gates": {},
            "supporting": {"schema": 1},
        },
    }


@pytest.mark.parametrize("content", [None, "not JSON", "[]"])
def test_missing_or_invalid_scope_sidecar_keeps_aggregate_evidence(tmp_path, content):
    doc = document()
    original = copy.deepcopy(doc["mutation"])
    path = tmp_path / "mutation-scopes.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    quality_measurements.add_mutation_scopes(doc["measurement_evidence"], doc, path)
    support = doc["measurement_evidence"]["mutation_scopes"]
    assert support["state"] == "UNAVAILABLE"
    assert support["scopes"] == []
    assert support["reason"]
    assert doc["mutation"] == original
    assert quality_dashboard.mutation_metric(doc)["status"] == "PASS"


def test_stale_scope_identity_is_not_accepted_as_current_measurement(tmp_path):
    doc = document()
    path = tmp_path / "mutation-scopes.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "sha": "c" * 40,
                "run_id": "41",
                "profile": "light",
                "state": "MEASURED",
                "scopes": [],
            }
        ),
        encoding="utf-8",
    )
    quality_measurements.add_mutation_scopes(doc["measurement_evidence"], doc, path)
    support = doc["measurement_evidence"]["mutation_scopes"]
    assert support["state"] == "UNAVAILABLE"
    assert not support["scopes"]


@pytest.mark.parametrize(
    ("counts", "state"),
    [
        ({"killed": 1, "survived": 0, "timeout": 1, "total": 2}, "UNAVAILABLE"),
        ({"killed": 0, "survived": 0, "total": 0}, "UNAVAILABLE"),
    ],
)
def test_incomplete_mutation_retains_proven_outcomes_without_a_score(
    tmp_path, counts, state
):
    doc = document()
    doc["mutation"]["counts"] = counts
    metric = doc["measurement_evidence"]["metrics"][0]
    metric.update(state="UNAVAILABLE", number=None, value="Unavailable", sources=[])
    path = tmp_path / "mutation-metrics.json"
    path.write_text(json.dumps(doc["mutation"]), encoding="utf-8")
    quality_measurements.add_mutation(doc["measurement_evidence"], doc, path)
    assert metric["sources"] and metric["state"] == state
    assert metric["number"] is None
    assert quality_dashboard.build_series(doc)["metrics"][-1]["status"] == "INCOMPLETE"


def test_additive_views_have_frozen_definition_and_context_identity():
    doc = document()
    quality_measurements.freeze_definitions(doc)
    quality_dashboard.build_supporting(doc)
    for key in ("mutation_scopes", "gate_decisions"):
        series = doc["series"][key]
        assert series["sha"] == SHA and series["run_id"] == "42"
        assert series["definition_identity"] == {
            k: doc["metric_definitions"][k] for k in ("catalog_sha256", "policy_sha256")
        }
    assert doc["series"]["mutation_scopes"]["state"] in {"PARTIAL", "UNAVAILABLE"}


@pytest.fixture
def retained_scopes(tmp_path, monkeypatch):
    from scripts.ci import measure_code_risk

    doc = document()
    helper = quality_measurements.module("avo_ci_mutation_scopes", "mutation_scopes.py")
    config = tmp_path / "mutation-config.json"
    config.write_text(
        json.dumps(
            {
                "light": {
                    "min_killed_percent": 40,
                    "source_paths": ["src/avo/a.py", "src/avo/b.py"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(helper, "CONFIG_PATH", config)
    nodes = []
    for name, codes in (("a", [1, 1, 0, 0]), ("b", [1, 1, 1, 1, 0, 0])):
        path = f"src/avo/{name}.py"
        source = tmp_path / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"def {name}():\n    return 1\n", encoding="utf-8")
        nodes.append(
            {"path": path, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        )
        metadata = tmp_path / ("mutants/" + path + ".meta")
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(
            json.dumps(
                {
                    "exit_code_by_key": {
                        f"avo.{name}.x_{name}__mutmut_{i}": code
                        for i, code in enumerate(codes)
                    }
                }
            ),
            encoding="utf-8",
        )
    stats = tmp_path / "mutants/mutmut-cicd-stats.json"
    stats.write_text(
        json.dumps(
            {
                "sha": SHA,
                "run_id": "42",
                "profile": "light",
                **doc["mutation"]["counts"],
            }
        ),
        encoding="utf-8",
    )
    payload = helper.capture_scopes(
        root=tmp_path, stats_path=stats, profile="light", sha=SHA, run_id="42"
    )
    directory = tmp_path / "reports/mutation"
    directory.mkdir(parents=True)
    for proof in [
        payload["aggregate"],
        *(row["metadata"] for row in payload["scopes"]),
    ]:
        target = directory / proof["artifact_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((tmp_path / proof["path"]).read_bytes())
    sidecar = directory / "mutation-scopes.json"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    metrics = directory / "mutation-metrics.json"
    metrics.write_text(json.dumps(doc["mutation"]), encoding="utf-8")
    quality_measurements.add_mutation(doc["measurement_evidence"], doc, metrics)
    graph = measure_code_risk._module_coupling(tmp_path / "src/avo", nodes)
    doc["measurement_evidence"]["supporting"]["coupling"] = (
        quality_measurements.validated_graph(
            graph, {row["path"]: row["sha256"] for row in nodes}
        )
    )
    assert doc["measurement_evidence"]["supporting"]["coupling"]["state"] == "MEASURED"
    return doc, sidecar, payload


def test_complete_scopes_bind_retained_bytes_source_hashes_and_aggregate(
    retained_scopes,
):
    doc, path, _ = retained_scopes
    quality_measurements.add_mutation_scopes(doc["measurement_evidence"], doc, path)
    support = doc["measurement_evidence"]["mutation_scopes"]
    assert support["state"] == "MEASURED", support["reason"]
    assert [row["score"] for row in support["scopes"]] == [50.0, 100 * 4 / 6]
    assert len(support["sources"]) == 4
    assert support["source_fingerprint"] == quality_measurements.canonical_digest(
        support["sources"]
    )


def test_all_five_frozen_views_round_trip_with_real_retained_scope_artifacts(
    retained_scopes,
):
    from scripts.ci import gen_kpi_charts

    doc, path, _ = retained_scopes
    quality_measurements.add_mutation_scopes(doc["measurement_evidence"], doc, path)
    quality_measurements.freeze_definitions(doc)
    quality_dashboard.build_supporting(doc)
    doc["series"]["dashboard"] = quality_dashboard.build_series(doc)
    frozen = gen_kpi_charts._frozen_report_series(
        doc, quality_dashboard, quality_measurements
    )
    assert set(frozen) == {
        "dashboard",
        "coupling_files",
        "hotspots",
        "mutation_scopes",
        "gate_decisions",
    }
    assert frozen["mutation_scopes"]["scopes"][0]["gate"] is None


def test_historical_three_role_catalog_does_not_require_new_supporting_views():
    from scripts.ci import gen_kpi_charts

    doc = document()
    quality_measurements.freeze_definitions(doc)
    quality_dashboard.build_supporting(doc)
    doc["series"]["dashboard"] = quality_dashboard.build_series(doc)
    block = doc["metric_definitions"]
    block["entries"] = [
        row
        for row in block["entries"]
        if row["id"] not in {"mutation_scopes", "gate_decisions"}
    ]
    block["catalog_sha256"] = quality_measurements.canonical_digest(
        {
            "schema": 1,
            "entries": [
                {key: value for key, value in row.items() if key != "sha256"}
                for row in block["entries"]
            ],
        }
    )
    assert (
        block["catalog_sha256"]
        == "56e97138760c15c40b497195e3a3ba6beb549aabd91b83d6cc7c885bdd90bb4e"
    )
    for role in ("mutation_scopes", "gate_decisions"):
        doc["series"].pop(role)
    for role in ("coupling_files", "hotspots"):
        doc["series"][role]["definition_identity"]["catalog_sha256"] = block[
            "catalog_sha256"
        ]
    frozen = gen_kpi_charts._frozen_report_series(
        doc, quality_dashboard, quality_measurements
    )
    assert set(frozen) == {"dashboard", "coupling_files", "hotspots"}
    assert (
        block["catalog_sha256"]
        == "56e97138760c15c40b497195e3a3ba6beb549aabd91b83d6cc7c885bdd90bb4e"
    )
    doc["series"]["mutation_scopes"] = {"chart": "mutation_scopes"}
    with pytest.raises(ValueError, match="no matching frozen metric definition"):
        gen_kpi_charts._frozen_report_series(
            doc, quality_dashboard, quality_measurements
        )


@pytest.mark.parametrize(
    "corruption",
    [
        "metadata_bytes",
        "metadata_bool",
        "aggregate_bytes",
        "source_hash",
        "unsafe_artifact",
    ],
)
def test_scope_proof_corruption_withholds_supporting_percentages(
    retained_scopes, corruption
):
    doc, path, payload = retained_scopes
    if corruption == "metadata_bytes":
        (path.parent / payload["scopes"][0]["metadata"]["artifact_path"]).write_text(
            "{}", encoding="utf-8"
        )
    elif corruption == "metadata_bool":
        proof = payload["scopes"][0]["metadata"]
        raw_path = path.parent / proof["artifact_path"]
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        raw["exit_code_by_key"][next(iter(raw["exit_code_by_key"]))] = True
        raw_path.write_text(json.dumps(raw), encoding="utf-8")
        proof["sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    elif corruption == "aggregate_bytes":
        (path.parent / payload["aggregate"]["artifact_path"]).write_text(
            "{}", encoding="utf-8"
        )
    elif corruption == "source_hash":
        payload["scopes"][0]["source_sha256"] = "f" * 64
    else:
        payload["scopes"][0]["metadata"]["artifact_path"] = "../untrusted.meta"
    path.write_text(json.dumps(payload), encoding="utf-8")
    quality_measurements.add_mutation_scopes(doc["measurement_evidence"], doc, path)
    support = doc["measurement_evidence"]["mutation_scopes"]
    assert support["state"] == "UNAVAILABLE"
    assert not support["scopes"]
    assert quality_dashboard.mutation_metric(doc)["status"] == "PASS"


def test_combiner_reads_scope_sidecar_next_to_same_run_mutation_metrics(
    tmp_path, monkeypatch
):
    doc = document()
    quality = tmp_path / "quality-metrics.json"
    quality.write_text(json.dumps(doc), encoding="utf-8")
    mutation = tmp_path / "evidence/mutation-metrics.json"
    mutation.parent.mkdir()
    mutation.write_text(json.dumps(doc["mutation"]), encoding="utf-8")
    calls = []
    measurements = write_unified_quality_report.load_module(
        "avo_ci_quality_measurements", "quality_measurements.py"
    )
    monkeypatch.setattr(
        measurements, "collect", lambda *_: copy.deepcopy(doc["measurement_evidence"])
    )
    monkeypatch.setattr(
        measurements, "add_mutation_scopes", lambda _e, _d, p: calls.append(p)
    )
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    for key in (
        "GITHUB_REPOSITORY",
        "GITHUB_EVENT_NAME",
        "GITHUB_EVENT_PATH",
        "GITHUB_RUN_ATTEMPT",
    ):
        monkeypatch.delenv(key, raising=False)
    write_unified_quality_report.combine(
        quality,
        mutation,
        sha=SHA,
        run_id="42",
        needs={key: {"result": "success"} for key in doc["jobs"]},
    )
    assert calls == [mutation.with_name("mutation-scopes.json")]


def test_inline_text_preserves_views_without_hosted_images():
    doc = document()
    quality_measurements.freeze_definitions(doc)
    quality_dashboard.build_supporting(doc)
    doc["mutation_image_error"] = "image generation failed"
    doc["gate_decisions_image_error"] = "image upload failed"
    text = quality_dashboard.markdown(doc, quality_dashboard.build_series(doc))
    assert "Mutation efficacy" in text
    assert "kpi-detail:mutation-efficacy.md" in text
    assert "kpi-detail:gate-decisions.md" in text
    assert "**Gate decisions**" in text
    assert "60.00%" in text
    assert "UNAVAILABLE" in text or "unavailable" in text


def test_verified_captured_gate_failure_cannot_leave_overall_green():
    doc = document()
    doc["measurement_evidence"]["metrics"] += [
        {"key": key, "state": "MEASURED", "number": number, "unit": "percent"}
        for key, number in (("coverage", 80.0), ("duplication", 0.5))
    ]
    doc["measurement_evidence"]["gates"] = {
        key: {"verified": True, "receipt": {"status": "PASS", "exit_code": 0}}
        for key, _ in GATES
    }
    assert quality_dashboard.build_series(doc)["overall"] == "PASS"
    doc["measurement_evidence"]["gates"]["lint"]["receipt"].update(
        status="FAIL", exit_code=1
    )
    result = quality_dashboard.build_series(doc)
    assert result["overall"] == "FAIL"
    assert any(
        "Lint" in action and "capture" in action.lower() for action in result["actions"]
    )
