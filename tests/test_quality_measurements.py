"""Measurements require saved execution receipts and their actual hashed outputs."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
RUN_ID = "42"
KEYS = (
    "coverage",
    "duplication",
    "mutation",
    "complexity",
    "crap",
    "coupling",
    "dependencies",
    "deadcode",
    "architecture",
    "tree",
    "branches",
)


def _load():
    spec = importlib.util.spec_from_file_location(
        "quality_measurements_test", ROOT / "scripts/ci/quality_measurements.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


@pytest.fixture
def execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Use the production wrapper with a fake analyzer, not fake validation."""
    collector = _load()
    wrapper = collector.module("avo_ci_gate_execution", "run_quality_gate.py")
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "_tee", lambda _chunk: None)
    source = tmp_path / "src" / "avo"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "sample.py").write_text(
        "def choose(value):\n    if value:\n        return 1\n    return 0\n\n"
        "def identity(value):\n    return value\n",
        encoding="utf-8",
    )
    directory = tmp_path / "reports" / "quality"
    directory.mkdir(parents=True)
    doc = {
        "sha": SHA,
        "run_id": RUN_ID,
        "mutation_policy": {"profile": "light", "floor": 40},
        "gates": [
            {"key": key, "title": key.title(), "status": "PASS"}
            for key in (
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
        ],
    }

    def produce(
        gate: str,
        outputs: dict[str, dict | str],
        *,
        log="Analyzer completed.\n",
        code=0,
    ):
        def process(*_args, **_kwargs):
            for name, payload in outputs.items():
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(payload, str):
                    path.write_text(payload, encoding="utf-8")
                else:
                    _write_json(path, payload)
            return SimpleNamespace(stdout=io.BytesIO(log.encode()), wait=lambda: code)

        monkeypatch.setattr(wrapper.subprocess, "Popen", process)
        args = [
            "--gate",
            gate,
            "--out-dir",
            str(directory / "gates"),
            "--sha",
            SHA,
            "--run-id",
            RUN_ID,
        ]
        for name in outputs:
            args.extend(["--artifact", str(directory / name)])
        args.extend(["--", "fixture-analyzer", gate])
        assert wrapper.main(args) == code
        receipt = directory / "gates" / gate / "gate.json"
        checked = wrapper.validate_receipt(
            receipt, sha=SHA, run_id=RUN_ID, gate=gate, artifact_root=directory
        )
        assert checked["valid"], checked["reason"]
        for row in doc["gates"]:
            if row["key"] == gate:
                row["status"] = "PASS" if code == 0 else "FAIL"
        return receipt

    return collector, doc, directory, produce


def _coverage() -> dict:
    return {
        "meta": {"format": 3, "branch_coverage": False},
        "totals": {"covered_lines": 7, "num_statements": 10, "percent_covered": 99.9},
    }


def _metrics(evidence: dict) -> dict:
    return {row["key"]: row for row in evidence["metrics"]}


def _audit(tool: str, payload: dict) -> dict:
    return {
        "schema_version": 1,
        "tool": tool,
        "sha": SHA,
        "run_id": RUN_ID,
        "recorded_at": "2026-10-14T12:00:00+00:00",
        "status": "COMPLETE",
        "exit_code": 0,
        "command": [tool, "audit"],
        "policy": {},
        "payload": payload,
        "error": None,
    }


def _dependencies() -> dict:
    """Match the producer: summary counters are top-level, not under counts."""
    counts = {"critical": 0, "high": 2, "moderate": 3, "low": 1}
    return {
        "npm-audit-summary.json": {"ok": True, **counts, "reported": [], "error": None},
        "deps-findings.json": {"findings": [], "error": None},
        "pip-audit-raw.json": _audit("pip", {"dependencies": []}),
        "npm-audit-raw.json": _audit(
            "npm",
            {
                "vulnerabilities": {
                    f"package-{severity}-{index}": {"severity": severity, "via": []}
                    for severity, total in counts.items()
                    for index in range(total)
                }
            },
        ),
    }


def _risk(directory: Path) -> dict:
    receipt = json.loads((directory / "gates/coverage/gate.json").read_text())
    return {
        "schema": 1,
        "sha": SHA,
        "run_id": RUN_ID,
        "recorded_at": "2026-10-14T12:00:00Z",
        "informational": True,
        "scope": "src/avo/**/*.py",
        "source_errors": [],
        "provenance": {
            "sources": receipt["source"]["end"],
            "coverage": {
                "path": "reports/quality/coverage.json",
                "sha256": _hash(directory / "coverage.json"),
                "status": "AVAILABLE",
                "binding": "validated receipt",
                "test_outcome": "success",
                "receipt": {
                    "path": "reports/quality/gates/coverage/gate.json",
                    "sha256": _hash(directory / "gates/coverage/gate.json"),
                },
            },
        },
        "functions": [
            {
                "path": "src/avo/sample.py",
                "qualname": "choose",
                "line": 1,
                "complexity": 2,
                "function_coverage": {
                    "status": "MEASURED",
                    "covered_lines": 2,
                    "num_statements": 3,
                    "percent": 200 / 3,
                },
                "crap": {"status": "MEASURED", "value": 2 + 4 / 27},
            },
            {
                "path": "src/avo/sample.py",
                "qualname": "identity",
                "line": 6,
                "complexity": 1,
                "function_coverage": {
                    "status": "MEASURED",
                    "covered_lines": 1,
                    "num_statements": 1,
                    "percent": 100.0,
                },
                "crap": {"status": "MEASURED", "value": 1.0},
            },
        ],
        "summary": {
            "function_count": 2,
            "max_complexity": 2,
            "complexity_status": "MEASURED",
            "max_crap": 2 + 4 / 27,
            "above_reference": 0,
            "measured_functions": 2,
            "unmeasured_functions": 0,
            "crap_status": "MEASURED",
        },
        "coupling": {
            "status": "MEASURED",
            "node_count": 2,
            "edge_count": 0,
            "packages": [
                {"package": "avo", "ca": 0, "ce": 0, "instability": None},
                {"package": "avo.sample", "ca": 0, "ce": 0, "instability": None},
            ],
        },
    }


def test_verified_counts_and_raw_artifact_references(execution) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": _coverage()})
    produce(
        "duplication",
        {
            "jscpd/jscpd-report.json": {
                "statistics": {
                    "total": {"duplicatedLines": 2, "lines": 250, "percentage": 0.8}
                },
                "duplicates": [{"firstFile": "a.py", "secondFile": "b.py"}],
            }
        },
    )
    produce("deps", _dependencies())
    produce(
        "deadcode",
        {
            "deadcode.json": {
                "sha": SHA,
                "run_id": RUN_ID,
                "complete": True,
                "counts": {"findings": 4, "unwaived": 1},
                "allowlisted": 999,
            }
        },
    )
    produce("architecture", {}, log="Contracts: 5 kept, 0 broken.\n")
    produce("tree", {"dependency-tree.json": {"added": 1, "removed": 0, "changed": 2}})
    evidence = collector.collect(doc, directory)
    assert evidence["schema"] == 1
    assert tuple(row["key"] for row in evidence["metrics"]) == KEYS
    rows = _metrics(evidence)
    assert rows["coverage"]["number"] == 70.0
    assert "7/10" in rows["coverage"]["basis"]
    assert rows["duplication"]["number"] == 0.8
    assert "2/250" in rows["duplication"]["basis"]
    assert (
        rows["dependencies"]["value"]
        == "0 blocking; npm 0 critical / 2 high / 3 moderate / 1 low"
    )
    assert rows["dependencies"]["state"] == "MEASURED"
    assert {source["path"] for source in rows["dependencies"]["sources"]} == {
        "npm-audit-summary.json",
        "deps-findings.json",
        "pip-audit-raw.json",
        "npm-audit-raw.json",
    }
    assert rows["deadcode"]["value"] == "4 reported; 1 unwaived"
    assert rows["architecture"]["value"] == "5 kept; 0 broken"
    assert rows["tree"]["value"] == "3 proposed package changes"
    assert rows["coverage"]["sources"] == [
        {
            "artifact": "quality-evidence",
            "path": "coverage.json",
            "sha256": _hash(directory / "coverage.json"),
        }
    ]
    proof = evidence["gates"]["coverage"]
    assert proof["verified"] is True
    assert [source["path"] for source in proof["sources"]] == [
        "gates/coverage/gate.json",
        "gates/coverage/gate.log",
    ]
    assert proof["sources"][1]["sha256"] == _hash(directory / "gates/coverage/gate.log")


def test_gate_decisions_are_not_metric_states(execution) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": _coverage()}, code=1)
    evidence = collector.collect(doc, directory)
    coverage = _metrics(evidence)["coverage"]
    assert evidence["gates"]["coverage"]["receipt"]["status"] == "FAIL"
    assert coverage["state"] == "PARTIAL" and coverage["number"] == 70.0
    assert all(
        "status" not in row and "threshold" not in row for row in evidence["metrics"]
    )


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "corrupt",
        "non_object_list",
        "non_object_string",
        "old_sha",
        "old_run",
        "wrong_gate",
        "wrong_outcome",
        "changed_log",
        "changed_output",
        "wrong_hash",
        "predates_command",
        "escaped_path",
    ],
)
def test_invalid_receipts_never_supply_zero_or_a_stale_value(
    execution, damage: str
) -> None:
    collector, doc, directory, produce = execution
    receipt_path = produce("coverage", {"coverage.json": _coverage()})
    receipt = json.loads(receipt_path.read_text())
    if damage == "missing":
        receipt_path.unlink()
    elif damage == "corrupt":
        receipt_path.write_text("{", encoding="utf-8")
    elif damage == "non_object_list":
        receipt_path.write_text("[{}]", encoding="utf-8")
    elif damage == "non_object_string":
        receipt_path.write_text('"invalid receipt"', encoding="utf-8")
    elif damage == "changed_log":
        (directory / "gates/coverage/gate.log").write_text("altered", encoding="utf-8")
    elif damage == "changed_output":
        _write_json(
            directory / "coverage.json",
            {"totals": {"covered_lines": 0, "num_statements": 10}},
        )
    else:
        if damage == "old_sha":
            receipt["sha"] = "b" * 40
        elif damage == "old_run":
            receipt["run_id"] = "41"
        elif damage == "wrong_gate":
            receipt["gate"] = "duplication"
        elif damage == "wrong_outcome":
            doc["gates"][2]["status"] = "SKIPPED"
        elif damage == "wrong_hash":
            receipt["artifacts"][0]["sha256"] = "0" * 64
        elif damage == "predates_command":
            receipt["artifacts"][0]["reason"] = "artifact predates command"
        elif damage == "escaped_path":
            receipt["artifacts"][0]["path"] = "reports/quality/../coverage.json"
        _write_json(receipt_path, receipt)
    result = collector.collect(doc, directory)
    row = _metrics(result)["coverage"]
    assert row["state"] == "UNAVAILABLE"
    assert row["number"] is None and row["value"] == "Unavailable"
    assert row["sources"] == []


def test_verified_but_unreadable_raw_json_remains_unavailable(execution) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": "{"})
    result = collector.collect(doc, directory)
    assert result["gates"]["coverage"]["verified"] is True
    assert _metrics(result)["coverage"]["number"] is None


@pytest.mark.parametrize("totals", [None, [], "invalid", 1])
def test_malformed_nested_coverage_totals_remain_unavailable(execution, totals) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": {"totals": totals}})
    result = collector.collect(doc, directory)
    assert result["gates"]["coverage"]["verified"] is True
    row = _metrics(result)["coverage"]
    assert row["state"] == "UNAVAILABLE" and row["number"] is None


@pytest.mark.parametrize(
    "totals",
    [
        {"duplicatedLines": 2, "lines": 250, "percentage": 99.9},
        {"duplicatedLines": 0, "lines": 250, "percentage": 1},
        None,
        [],
    ],
)
def test_malformed_or_contradictory_duplication_is_not_a_measurement(
    execution, totals
) -> None:
    collector, doc, directory, produce = execution
    produce(
        "duplication",
        {
            "jscpd/jscpd-report.json": {
                "statistics": {"total": totals},
                "duplicates": [],
            }
        },
    )
    row = _metrics(collector.collect(doc, directory))["duplication"]
    assert row["state"] == "UNAVAILABLE" and row["number"] is None


@pytest.mark.parametrize("total, reported", [(300, 0.33), (60, 1.66)])
def test_rounded_duplication_percentage_matches_observed_lines(
    execution, total: int, reported: float
) -> None:
    collector, doc, directory, produce = execution
    produce(
        "duplication",
        {
            "jscpd/jscpd-report.json": {
                "statistics": {
                    "total": {
                        "duplicatedLines": 1,
                        "lines": total,
                        "percentage": reported,
                    }
                },
                "duplicates": [],
            }
        },
    )
    row = _metrics(collector.collect(doc, directory))["duplication"]
    assert row["state"] == "MEASURED"
    assert row["number"] == pytest.approx(100 / total)
    assert row["value"] == f"{row['number']:.2f}%"
    assert f"1/{total}" in row["basis"]


@pytest.mark.parametrize(
    "damage",
    [
        "missing_pip",
        "missing_npm",
        "pip_not_run",
        "npm_error",
        "pip_old_sha",
        "npm_old_run",
    ],
)
def test_dependency_summaries_flag_incomplete_or_unbound_raw_audits(
    execution, damage: str
) -> None:
    collector, doc, directory, produce = execution
    outputs = _dependencies()
    if damage.startswith("missing"):
        del outputs[f"{damage.rsplit('_', 1)[1]}-audit-raw.json"]
    elif damage == "pip_not_run":
        outputs["pip-audit-raw.json"].update(
            status="NOT_RUN", exit_code=None, payload=None, error="audit has not run"
        )
    elif damage == "npm_error":
        outputs["npm-audit-raw.json"].update(
            status="ERROR", exit_code=2, payload=None, error="registry unavailable"
        )
    elif damage == "pip_old_sha":
        outputs["pip-audit-raw.json"]["sha"] = "b" * 40
    elif damage == "npm_old_run":
        outputs["npm-audit-raw.json"]["run_id"] = "41"
    produce("deps", outputs)
    row = _metrics(collector.collect(doc, directory))["dependencies"]
    assert row["state"] == "PARTIAL"
    assert row["value"] == "0 blocking; npm 0 critical / 2 high / 3 moderate / 1 low"
    assert "Raw audit incomplete" in row["basis"]
    tool = "pip" if "pip" in damage else "npm"
    expected = (
        "NOT_RUN"
        if damage == "pip_not_run"
        else "ERROR"
        if damage == "npm_error"
        else "capture unavailable"
    )
    assert f"{tool}: {expected}" in row["basis"]


def test_configuration_counts_cannot_substitute_for_analyzer_output(execution) -> None:
    collector, doc, directory, _produce = execution
    doc["series"] = {
        "complexity": {"count": 178},
        "deadcode": {"count": 150},
        "architecture": {"count": 5},
    }
    rows = _metrics(collector.collect(doc, directory))
    assert all(
        rows[key]["state"] == "UNAVAILABLE"
        for key in ("complexity", "deadcode", "architecture")
    )


def test_architecture_zero_is_measured_only_from_executed_contract_output(
    execution,
) -> None:
    collector, doc, directory, produce = execution
    produce("architecture", {}, log="import-linter ran successfully\n")
    result = collector.collect(doc, directory)
    assert result["gates"]["architecture"]["verified"] is True
    assert _metrics(result)["architecture"]["state"] == "UNAVAILABLE"
    produce("architecture", {}, log="\x1b[32mContracts: 5 kept, 0 broken.\x1b[0m\n")
    assert (
        _metrics(collector.collect(doc, directory))["architecture"]["value"]
        == "5 kept; 0 broken"
    )


def test_line_profile_does_not_claim_safety_branch_coverage(execution) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": _coverage()})
    row = _metrics(collector.collect(doc, directory))["branches"]
    assert row["state"] == "UNAVAILABLE" and row["number"] is None
    assert "does not instrument branches" in row["basis"]


def test_code_risk_needs_its_own_receipt_even_with_matching_identity(execution) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": _coverage()})
    _write_json(directory / "code-risk.json", _risk(directory))
    rows = _metrics(collector.collect(doc, directory))
    assert all(
        rows[key]["state"] == "UNAVAILABLE"
        for key in ("complexity", "crap", "coupling")
    )


def test_code_risk_uses_verified_output_and_real_coverage_input_receipt(
    execution,
) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": _coverage()})
    produce("code-risk", {"code-risk.json": _risk(directory)})
    result = collector.collect(doc, directory)
    rows = _metrics(result)
    assert rows["complexity"]["number"] == 2
    assert rows["crap"]["number"] == pytest.approx(2 + 4 / 27)
    assert rows["crap"]["state"] == "MEASURED"
    assert rows["coupling"]["state"] == "MEASURED"
    assert "Maximum CA 0 / CE 0" in rows["coupling"]["value"]
    assert result["diagnostics"]["code_risk"]["functions"][0]["line"] == 1
    assert rows["crap"]["sources"][0]["path"] == "code-risk.json"


def test_crap_preserves_producer_incompleteness_after_a_source_parse_error(
    execution,
) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": _coverage()})
    risk = _risk(directory)
    risk["source_errors"] = ["src/avo/unreadable.py: source parse failed"]
    risk["summary"].update(complexity_status="INCOMPLETE", crap_status="INCOMPLETE")
    produce("code-risk", {"code-risk.json": risk})
    rows = _metrics(collector.collect(doc, directory))
    assert rows["complexity"]["state"] == "PARTIAL"
    assert rows["crap"]["state"] == "PARTIAL"
    assert rows["crap"]["number"] == pytest.approx(2 + 4 / 27)


def test_code_risk_cannot_claim_validated_coverage_after_receipt_loss(
    execution,
) -> None:
    collector, doc, directory, produce = execution
    input_receipt = produce("coverage", {"coverage.json": _coverage()})
    produce("code-risk", {"code-risk.json": _risk(directory)})
    input_receipt.unlink()
    rows = _metrics(collector.collect(doc, directory))
    assert rows["crap"]["state"] == "UNAVAILABLE" and rows["crap"]["number"] is None


def test_code_risk_cannot_reuse_a_different_valid_coverage_execution(execution) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": _coverage()})
    produce("code-risk", {"code-risk.json": _risk(directory)})
    changed = _coverage()
    changed["totals"]["covered_lines"] = 8
    produce("coverage", {"coverage.json": changed})
    result = collector.collect(doc, directory)
    assert result["gates"]["coverage"]["verified"] is True
    rows = _metrics(result)
    assert rows["coverage"]["number"] == 80.0
    assert rows["crap"]["state"] == "UNAVAILABLE" and rows["crap"]["number"] is None


@pytest.mark.parametrize("damage", ["source_hash", "source_changed", "input_failed"])
def test_crap_requires_successful_coverage_of_the_same_unchanged_sources(
    execution, damage: str
) -> None:
    collector, doc, directory, produce = execution
    receipt_path = produce(
        "coverage", {"coverage.json": _coverage()}, code=int(damage == "input_failed")
    )
    if damage == "source_changed":
        receipt = json.loads(receipt_path.read_text())
        receipt["source"]["unchanged"] = False
        _write_json(receipt_path, receipt)
    risk = _risk(directory)
    if damage == "source_hash":
        risk["provenance"]["sources"]["sha256"] = "b" * 64
    produce("code-risk", {"code-risk.json": risk})
    row = _metrics(collector.collect(doc, directory))["crap"]
    assert row["state"] == "UNAVAILABLE" and row["number"] is None


@pytest.mark.parametrize(
    "counts",
    [
        {"covered_lines": 0, "num_statements": 0},
        {"covered_lines": 3, "num_statements": 2},
        {"covered_lines": True, "num_statements": 10},
        {"covered_lines": 0, "num_statements": -1},
        {"percent_covered": 100},
    ],
)
def test_invalid_coverage_counts_are_unmeasured_not_zero(
    execution, counts: dict
) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": {"totals": counts}})
    row = _metrics(collector.collect(doc, directory))["coverage"]
    assert row["state"] == "UNAVAILABLE" and row["number"] is None


@pytest.mark.parametrize(
    "damage", ["receipt_run", "receipt_shape", "output_sha", "output_hash"]
)
def test_code_risk_identity_and_hash_changes_are_rejected(
    execution, damage: str
) -> None:
    collector, doc, directory, produce = execution
    produce("coverage", {"coverage.json": _coverage()})
    risk = _risk(directory)
    if damage == "output_sha":
        risk["sha"] = "b" * 40
    receipt_path = produce("code-risk", {"code-risk.json": risk})
    if damage == "receipt_run":
        receipt = json.loads(receipt_path.read_text())
        receipt["run_id"] = "41"
        _write_json(receipt_path, receipt)
    elif damage == "receipt_shape":
        receipt_path.write_text("[{}]", encoding="utf-8")
    elif damage == "output_hash":
        risk["summary"]["max_crap"] = 0
        _write_json(directory / "code-risk.json", risk)
    rows = _metrics(collector.collect(doc, directory))
    assert all(
        rows[key]["state"] == "UNAVAILABLE"
        for key in ("complexity", "crap", "coupling")
    )


def _mutation() -> dict:
    return {
        "sha": SHA,
        "run_id": RUN_ID,
        "profile": "light",
        "floor": 40,
        "counts": {"killed": 3, "survived": 1, "total": 4},
    }


def test_complete_mutation_counts_and_artifact_reference(execution) -> None:
    collector, doc, directory, _produce = execution
    doc["mutation"] = _mutation()
    path = directory / "mutation-metrics.json"
    _write_json(path, doc["mutation"])
    result = collector.collect(doc, directory)
    collector.add_mutation(result, doc, path)
    row = _metrics(result)["mutation"]
    assert row["state"] == "MEASURED" and row["number"] == 75.0
    assert "3 killed / 1 survived / 4 total; 0 unresolved" in row["basis"]
    assert row["sources"] == [
        {
            "artifact": "mutation-reports-light",
            "path": "mutation-metrics.json",
            "sha256": _hash(path),
        }
    ]


@pytest.mark.parametrize(
    "damage",
    ["missing", "old_sha", "old_run", "unaccounted", "timeout", "file_mismatch"],
)
def test_untrusted_or_incomplete_mutation_is_not_a_zero_score(
    execution, damage: str
) -> None:
    collector, doc, directory, _produce = execution
    payload = _mutation()
    if damage == "old_sha":
        payload["sha"] = "b" * 40
    elif damage == "old_run":
        payload["run_id"] = "41"
    elif damage == "unaccounted":
        payload["counts"]["total"] = 5
    elif damage == "timeout":
        payload["counts"].update(timeout=1, total=5)
    doc["mutation"] = copy.deepcopy(payload)
    if damage == "file_mismatch":
        payload["counts"]["killed"] = 2
    path = directory / "mutation-metrics.json"
    if damage != "missing":
        _write_json(path, payload)
    result = collector.collect(doc, directory)
    collector.add_mutation(result, doc, path)
    row = _metrics(result)["mutation"]
    assert row["state"] == "UNAVAILABLE" and row["number"] is None
    assert row["sources"] == []
