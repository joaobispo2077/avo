"""Categorical gate decisions stay distinct from proof and job populations."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATES = (
    "lint",
    "format",
    "coverage",
    "complexity",
    "deps",
    "deadcode",
    "duplication",
    "architecture",
    "tree",
)
JOBS = (
    "prerequisites-gate",
    "repo-unit-tests",
    "repo-integration-tests",
    "software-quality",
    "usability-gate",
    "mutation-light",
    "ci-readiness",
)


def helper():
    spec = importlib.util.spec_from_file_location(
        "test_gate_view", ROOT / "scripts/ci/quality_gate_decisions.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def document():
    # A measured aggregate with controlled values, not a live CI claim.
    return {
        "sha": "a" * 40,
        "run_id": "42",
        "reporting": {"mode": "fixture"},
        "mutation_policy": {"profile": "light", "floor": 60},
        "mutation": {
            "sha": "a" * 40,
            "run_id": "42",
            "profile": "light",
            "floor": 60,
            "counts": {"killed": 8, "survived": 2, "total": 10},
        },
        "coverage_precision": 0,
        "floor": 68,
        "series": {"coverage": {"floor": 68}, "duplication": {"ceiling": 2}},
        "gates": [
            {
                "key": key,
                "title": key.title(),
                "status": "PASS",
                "checks": "Captured policy " + key,
                "metric": "Configuration count must not become a measured score",
            }
            for key in GATES
        ],
        "jobs": dict.fromkeys(JOBS, "success"),
        "measurement_evidence": {
            "schema": 1,
            "gates": {
                key: {
                    "verified": True,
                    "reason": "Verified execution and hashes.",
                    "receipt": {"status": "PASS", "exit_code": 0},
                    "sources": [
                        {
                            "artifact": "quality-evidence",
                            "path": f"gates/{key}/gate.json",
                            "sha256": "b" * 64,
                        }
                    ],
                }
                for key in GATES
            },
            "metrics": [
                {
                    "key": "mutation",
                    "state": "MEASURED",
                    "number": 80,
                    "unit": "percent",
                    "sources": [
                        {
                            "artifact": "mutation-reports-light",
                            "path": "mutation-metrics.json",
                            "sha256": "c" * 64,
                        }
                    ],
                },
                {
                    "key": "coverage",
                    "state": "MEASURED",
                    "number": 71.5,
                    "unit": "percent",
                    "value": "71.50%",
                    "basis": "143/200 executable lines",
                    "sources": [],
                },
                {
                    "key": "deadcode",
                    "state": "MEASURED",
                    "value": "150 reported; 0 unwaived",
                    "basis": "Observed findings",
                    "sources": [],
                },
            ],
        },
    }


def test_ten_categorical_decisions_keep_actual_proof_and_separate_jobs():
    doc = document()
    before = copy.deepcopy(doc)
    series = helper().build_gate_series(doc)
    assert doc == before and series["state"] == "MEASURED"
    assert len(series["rows"]) == 10 and series["counts"]["PASS"] == 10
    assert series["verified_proofs"] == 10 and series["required_jobs"] == doc["jobs"]
    assert all(row["proof"] == "VERIFIED" for row in series["rows"])
    lint = series["rows"][0]
    assert "0" in lint["observed"] and "not exported" in lint["observed"]
    assert "0 issues" not in lint["observed"] and "percent" not in lint["observed"]
    assert next(r for r in series["rows"] if r["key"] == "deadcode")[
        "observed"
    ].startswith("150 reported")
    assert "68%" in next(r for r in series["rows"] if r["key"] == "coverage")["policy"]
    assert (
        "60%" in series["rows"][-1]["policy"]
        and "aggregate" in series["rows"][-1]["policy"]
    )


@pytest.mark.parametrize("missing", ["unverified", "absent_receipt", "absent_gate"])
def test_reported_pass_without_proof_is_never_a_green_verified_decision(missing):
    doc = document()
    if missing == "unverified":
        doc["measurement_evidence"]["gates"]["lint"].update(
            verified=False, reason="Hash mismatch"
        )
    elif missing == "absent_receipt":
        doc["measurement_evidence"]["gates"].pop("lint")
    else:
        doc["gates"].pop(0)
    series = helper().build_gate_series(doc)
    row = series["rows"][0]
    assert row["decision"] in {"INCOMPLETE", "MISSING"} and row["proof"] != "VERIFIED"
    assert series["counts"]["PASS"] == 9 and series["state"] == "PARTIAL"
    if missing != "absent_gate":
        assert row["reported_decision"] == "PASS"


@pytest.mark.parametrize(
    ("reported", "receipt", "reason", "expected"),
    [
        ("FAIL", "FAIL", "Command failed", "FAIL"),
        ("FAIL", "CANCELLED", "Interrupted", "CANCELED"),
        ("FAIL", "ERROR", "Timed out after 20 minutes", "TIMEOUT"),
        ("SKIPPED", "SKIPPED", "Skipped by selector", "SKIPPED"),
        ("INCOMPLETE", "INCOMPLETE", "Missing results", "INCOMPLETE"),
    ],
)
def test_failed_canceled_timeout_skipped_and_incomplete_remain_distinct(
    reported, receipt, reason, expected
):
    doc = document()
    doc["gates"][0]["status"] = reported
    doc["measurement_evidence"]["gates"]["lint"]["receipt"].update(
        status=receipt, exit_code=None, error=reason
    )
    series = helper().build_gate_series(doc)
    assert series["rows"][0]["decision"] == expected
    assert series["rows"][0]["proof"] == "VERIFIED"


def test_missing_all_evidence_is_unavailable_and_required_absence_is_explicit():
    series = helper().build_gate_series({})
    assert series["state"] == "UNAVAILABLE" and series["counts"].get("PASS", 0) == 0
    assert series["verified_proofs"] == 0 and all(
        v == "unknown" for v in series["required_jobs"].values()
    )


def test_verified_receipt_failure_overrides_reported_pass_without_hiding_it():
    doc = document()
    doc["measurement_evidence"]["gates"]["lint"]["receipt"].update(
        status="FAIL", exit_code=1
    )
    row = helper().build_gate_series(doc)["rows"][0]
    assert row["decision"] == "FAIL" and row["reported_decision"] == "PASS"
    assert row["proof"] == "VERIFIED"


def test_dependency_yellow_band_paints_the_chip_and_metric(tmp_path):
    from PIL import Image

    mod = helper()
    doc = document()
    named = (
        "PASS, 0 critical, 3 high, 0 moderate, 0 low: "
        "braces@3.0.3 GHSA-vfj7-8cjw-p6xm, sharp, source-map-js"
    )
    doc["measurement_evidence"]["metrics"].append(
        {
            "key": "dependencies",
            "state": "MEASURED",
            "value": named,
            "band": "yellow",
            "basis": "High findings pass.",
            "sources": [],
        }
    )
    series = mod.build_gate_series(doc)
    row = next(item for item in series["rows"] if item["key"] == "deps")
    assert row["decision"] == "PASS"
    assert row["band"] == "yellow"
    assert row["observed"] == named
    assert mod.validate_frozen_series(series, doc) is True
    mod.render_gates(series, tmp_path / "gate-decisions.png")
    with Image.open(tmp_path / "gate-decisions.png") as image:
        rgb = image.convert("RGB")
        assert json.loads(image.info["Description"])["rows"]
    yellow = False
    amber_text = False
    width, height = rgb.size
    pix = rgb.load()
    for y in range(height):
        for x in range(width):
            red, green, blue = pix[x, y]
            if abs(red - 240) <= 12 and abs(green - 180) <= 20 and blue <= 30:
                yellow = True
            if abs(red - 133) <= 12 and abs(green - 93) <= 12 and blue <= 20:
                amber_text = True
    assert yellow and amber_text


def test_dependency_gate_uses_observed_findings_not_a_missing_alias():
    doc = document()
    doc["measurement_evidence"]["metrics"].append(
        {
            "key": "dependencies",
            "state": "MEASURED",
            "value": "0 blocking; npm 0 critical / 2 high / 7 moderate / 0 low",
            "basis": "Only unwaived Python findings and npm critical findings block.",
            "sources": [],
        }
    )
    row = next(
        row for row in helper().build_gate_series(doc)["rows"] if row["key"] == "deps"
    )
    assert row["observed"] == "0 blocking; npm 0 critical / 2 high / 7 moderate / 0 low"
    assert row["decision"] == "PASS"


def test_verified_receipt_pass_never_overrides_reported_failure():
    doc = document()
    doc["gates"][0]["status"] = "FAIL"
    assert helper().build_gate_series(doc)["rows"][0]["decision"] == "FAIL"


@pytest.mark.parametrize("flag", ["true", 1, "false"])
def test_nonboolean_verified_flag_cannot_produce_a_verified_pass(flag):
    doc = document()
    doc["measurement_evidence"]["gates"]["lint"]["verified"] = flag
    row = helper().build_gate_series(doc)["rows"][0]
    assert row["proof"] == "UNVERIFIED" and row["decision"] == "INCOMPLETE"


@pytest.mark.parametrize(("key", "number"), [("coverage", 50), ("duplication", 3)])
def test_actual_primary_policy_failure_overrides_reported_pass(key, number):
    doc = document()
    doc["measurement_evidence"]["metrics"] = [
        r for r in doc["measurement_evidence"]["metrics"] if r["key"] != key
    ]
    doc["measurement_evidence"]["metrics"].append(
        {
            "key": key,
            "state": "MEASURED",
            "number": number,
            "value": f"{number}%",
            "unit": "percent",
            "sources": [],
        }
    )
    row = next(
        row for row in helper().build_gate_series(doc)["rows"] if row["key"] == key
    )
    assert row["decision"] == "FAIL" and row["reported_decision"] == "PASS"


@pytest.mark.parametrize("key", ["coverage", "duplication"])
@pytest.mark.parametrize(
    ("status", "expected"), [("CANCELLED", "CANCELED"), ("TIMEOUT", "TIMEOUT")]
)
def test_primary_policy_cannot_hide_specific_execution_failure(key, status, expected):
    doc = document()
    next(row for row in doc["gates"] if row["key"] == key)["status"] = "FAIL"
    doc["measurement_evidence"]["gates"][key]["receipt"].update(
        status=status, exit_code=None
    )
    row = next(
        row for row in helper().build_gate_series(doc)["rows"] if row["key"] == key
    )
    assert row["decision"] == expected and row["reported_decision"] == "FAIL"


def test_malformed_frozen_shape_raises_value_error():
    mod = helper()
    doc = document()
    series = mod.build_gate_series(doc)
    series["sources"] = None
    with pytest.raises(ValueError):
        mod.validate_frozen_series(series, doc)


def test_text_and_png_bind_the_same_decisions_and_dynamic_policy(tmp_path):
    from PIL import Image

    mod = helper()
    doc = document()
    series = mod.build_gate_series(doc)
    outputs = mod.write_gate_indexes(series, tmp_path)
    assert (
        outputs["json"].name == "gate-decisions.json"
        and json.loads(outputs["json"].read_text()) == series
    )
    text = outputs["markdown"].read_text(encoding="utf-8")
    assert "68%" in text and "60%" in text and "0 decimal" in text
    assert "150 reported" in text and "mutation-metrics.json" in text
    assert all(name in text for name in JOBS)
    mod.render_gates(series, tmp_path / "gate-decisions.png")
    with Image.open(tmp_path / "gate-decisions.png") as image:
        assert json.loads(image.info["Description"]) == series
    assert mod.validate_frozen_series(series, doc) is True


def test_frozen_validation_never_rebuilds_current_presentations(monkeypatch):
    mod = helper()
    doc = document()
    series = mod.build_gate_series(doc)
    series["rows"].reverse()
    series["rows"][0].update(
        title="Historical mutation label", policy="Historical policy wording."
    )
    before = copy.deepcopy(series)

    def fail(*_args, **_kwargs):
        raise AssertionError("Current gate presentation was rebuilt")

    monkeypatch.setattr(mod, "build_gate_series", fail)
    monkeypatch.setattr(mod._view(), "build_mutation_series", fail)
    monkeypatch.setattr(mod._view().load("quality_dashboard"), "build_series", fail)
    assert mod.validate_frozen_series(series, doc) is True
    assert series == before


def test_frozen_unavailable_null_mutation_does_not_require_reconstruction(monkeypatch):
    mod = helper()
    doc = document()
    doc["mutation"] = None
    doc["measurement_evidence"]["metrics"][0].update(state="UNAVAILABLE", number=None)
    series = mod.build_gate_series(doc)
    monkeypatch.setattr(
        mod, "build_gate_series", lambda *_a, **_kw: pytest.fail("rebuilt")
    )
    assert series["rows"][-1]["decision"] == "UNAVAILABLE"
    assert mod.validate_frozen_series(series, doc) is True


def test_frozen_required_job_population_cannot_hide_a_captured_failure():
    mod = helper()
    doc = document()
    doc["jobs"]["repo-unit-tests"] = "failure"
    series = mod.build_gate_series(doc)
    del series["required_jobs"]["repo-unit-tests"]
    with pytest.raises(ValueError, match="required-job"):
        mod.validate_frozen_series(series, doc)


def test_frozen_gate_population_cannot_hide_a_missing_capture():
    mod = helper()
    doc = document()
    doc["gates"] = [gate for gate in doc["gates"] if gate["key"] != "architecture"]
    series = mod.build_gate_series(doc)
    series["rows"] = [row for row in series["rows"] if row["key"] != "architecture"]
    del series["counts"]["MISSING"]
    series.update(total=9, state="MEASURED")
    with pytest.raises(ValueError, match="population"):
        mod.validate_frozen_series(series, doc)


@pytest.mark.parametrize("change", ["proof", "status", "counts", "fingerprint"])
def test_frozen_validation_rejects_false_proof_decision_or_summary(change):
    mod = helper()
    doc = document()
    series = mod.build_gate_series(doc)
    if change == "proof":
        series["rows"][0]["proof"] = "MISSING"
    elif change == "status":
        series["rows"][0]["decision"] = "FAIL"
    elif change == "counts":
        series["counts"]["PASS"] = 99
    else:
        series["source_fingerprint"] = "0" * 64
    with pytest.raises(ValueError):
        mod.validate_frozen_series(series, doc)


def test_render_failure_keeps_indexes_and_removes_stale_png(tmp_path, monkeypatch):
    from matplotlib.figure import Figure

    mod = helper()
    series = mod.build_gate_series(document())
    outputs = mod.write_gate_indexes(series, tmp_path)
    path = tmp_path / "gate-decisions.png"
    path.write_bytes(b"old")

    def fail(*_args, **_kwargs):
        raise OSError("Disk full")

    monkeypatch.setattr(Figure, "savefig", fail)
    with pytest.raises(OSError):
        mod.render_gates(series, path)
    assert not path.exists() and outputs["markdown"].exists()
