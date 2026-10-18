from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
RUN_ID = "42"


def metric_module():
    spec = importlib.util.spec_from_file_location(
        "code_risk_metrics", ROOT / "scripts/ci/measure_code_risk.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sources(tmp_path, source):
    package = tmp_path / "src" / "avo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "logic.py").write_text(source, encoding="utf-8")
    return package


def function(start_line, executed, missing):
    return {
        "start_line": start_line,
        "executed_lines": executed,
        "missing_lines": missing,
        "excluded_lines": [],
        "summary": {
            "covered_lines": len(executed),
            "num_statements": len(executed) + len(missing),
            "missing_lines": len(missing),
            "percent_covered": 100,
        },
    }


def coverage(tmp_path, functions, *, filename="src/avo/logic.py", provenance=None):
    path = tmp_path / "coverage.json"
    profile = {
        "meta": {"format": 3, "version": "test"},
        "files": {
            filename: {"summary": {"percent_covered": 100}, "functions": functions}
        },
        "totals": {"percent_covered": 100},
    }
    if provenance is not None:
        profile["provenance"] = provenance
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def report(mod, tmp_path, profile, **kwargs):
    return mod.build_report(
        root=tmp_path,
        coverage_path=profile,
        sha=SHA,
        run_id=RUN_ID,
        recorded_at="2026-10-14T12:00:00Z",
        test_outcome=kwargs.pop("test_outcome", "success"),
        **kwargs,
    )


def test_known_crap_formula_and_reference_is_informational():
    mod = metric_module()
    assert mod.crap_score(6, 0) == 42
    assert mod.crap_score(10, 50) == 22.5
    assert mod.crap_score(10, 100) == 10
    assert mod.CRAP_REFERENCE == 30


def test_report_counts_observed_crap_above_informational_reference(tmp_path):
    source = (
        "def risky(x):\n"
        + "".join(
            f"    if x == {index}:\n        return {index}\n" for index in range(5)
        )
        + "    return -1\n"
    )
    sources(tmp_path, source)
    profile = coverage(tmp_path, {"risky": function(1, [], list(range(2, 13)))})
    document = report(metric_module(), tmp_path, profile)
    assert document["summary"]["max_complexity"] == 6
    assert document["summary"]["max_crap"] == 42
    assert document["summary"]["above_reference"] == 1
    assert document["informational"] is True


@pytest.mark.parametrize("ci", ("false", "true"))
def test_cli_requires_explicit_success_and_ci_receipt(tmp_path, ci):
    sources(tmp_path, "def work(x):\n    return x\n")
    profile = coverage(tmp_path, {"work": function(1, [2], [])})
    out = tmp_path / "risk.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/ci/measure_code_risk.py"),
        "--root",
        str(tmp_path),
        "--coverage",
        str(profile),
        "--out",
        str(out),
        "--sha",
        SHA,
        "--run-id",
        RUN_ID,
    ]
    if ci == "true":
        command += ["--test-outcome", "success"]
    result = subprocess.run(
        command,
        env={**os.environ, "GITHUB_ACTIONS": ci},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["summary"]["max_complexity"] == 1
    assert document["summary"]["max_crap"] is None
    assert document["schema"] == 1
    assert document["sha"] == SHA and document["run_id"] == RUN_ID


def test_crap_uses_each_functions_line_counts_not_file_or_branch_percentage(tmp_path):
    sources(
        tmp_path,
        "def uncovered(x):\n    if x:\n        return 1\n    return 0\n\ndef covered(x):\n    return x\n",
    )
    profile = coverage(
        tmp_path,
        {"uncovered": function(1, [], [2, 3, 4]), "covered": function(6, [7], [])},
    )
    document = report(metric_module(), tmp_path, profile)
    rows = {row["qualname"]: row for row in document["functions"]}
    assert rows["uncovered"]["complexity"] == 2
    assert rows["uncovered"]["function_coverage"]["percent"] == 0
    assert rows["uncovered"]["crap"]["value"] == 6
    assert rows["covered"]["function_coverage"]["percent"] == 100
    assert rows["covered"]["crap"]["value"] == 1
    assert rows["covered"]["crap"]["informational"] is True
    assert document["summary"]["max_crap"] == 6
    assert document["summary"]["measured_functions"] == 2


def test_nested_functions_classes_and_async_methods_have_exact_identity(tmp_path):
    sources(
        tmp_path,
        "class Outer:\n    def method(self):\n        def inner(x):\n            if x:\n                return x\n            return 0\n        return inner(1)\n    class Inner:\n        async def method(self):\n            return 1\n",
    )
    profile = coverage(
        tmp_path,
        {
            "Outer.method": function(2, [3, 7], []),
            "Outer.method.inner": function(3, [], [4, 5, 6]),
            "Outer.Inner.method": function(9, [10], []),
        },
    )
    document = report(metric_module(), tmp_path, profile)
    rows = {row["qualname"]: row for row in document["functions"]}
    assert set(rows) == {"Outer.method", "Outer.method.inner", "Outer.Inner.method"}
    assert rows["Outer.method"]["complexity"] == 1
    assert rows["Outer.method"]["crap"]["value"] == 1
    assert rows["Outer.method.inner"]["complexity"] == 2
    assert rows["Outer.method.inner"]["crap"]["value"] == 6
    assert (
        rows["Outer.Inner.method"]["id"]
        == "avo.logic.Outer.Inner.method@src/avo/logic.py:9"
    )


def test_duplicate_callable_name_never_reuses_other_definition_coverage(tmp_path):
    sources(tmp_path, "def same():\n    return 1\n\ndef same():\n    return 2\n")
    document = report(
        metric_module(),
        tmp_path,
        coverage(tmp_path, {"same": function(4, [5], [])}),
    )
    assert document["functions"][0]["crap"]["value"] is None
    assert document["functions"][1]["crap"]["value"] == 1
    assert document["functions"][0]["id"] != document["functions"][1]["id"]


def test_missing_coverage_keeps_complexity_and_coupling_without_inventing_crap(
    tmp_path,
):
    sources(tmp_path, "def work(x):\n    return x\n")
    document = report(metric_module(), tmp_path, tmp_path / "absent.json")
    assert document["summary"]["max_complexity"] == 1
    assert document["summary"]["max_crap"] is None
    assert document["summary"]["above_reference"] is None
    assert document["summary"]["unmeasured_functions"] == 1
    assert document["coupling"]["status"] == "MEASURED"
    assert document["functions"][0]["function_coverage"]["percent"] is None


def test_file_average_alone_cannot_supply_function_crap(tmp_path):
    sources(tmp_path, "def work(x):\n    return x\n")
    profile = coverage(tmp_path, {})
    document = report(metric_module(), tmp_path, profile)
    assert document["summary"]["measured_functions"] == 0
    assert document["summary"]["max_crap"] is None


def test_outer_function_never_inherits_nested_body_coverage(tmp_path):
    sources(
        tmp_path,
        "def outer():\n    def inner():\n        return 1\n    return inner()\n",
    )
    profile = coverage(
        tmp_path,
        {
            "outer": function(1, [2, 3, 4], []),
            "outer.inner": function(2, [3], []),
        },
    )
    document = report(metric_module(), tmp_path, profile)
    rows = {row["qualname"]: row for row in document["functions"]}
    assert rows["outer"]["crap"]["value"] is None
    assert rows["outer.inner"]["crap"]["value"] == 1


def test_invalid_json_still_records_input_hash_and_source_measurements(tmp_path):
    sources(tmp_path, "def work(x):\n    return x\n")
    profile = tmp_path / "coverage.json"
    profile.write_text("{", encoding="utf-8")
    document = report(metric_module(), tmp_path, profile)
    assert len(document["provenance"]["coverage"]["sha256"]) == 64
    assert document["summary"]["max_complexity"] == 1
    assert document["summary"]["max_crap"] is None


def test_sources_changing_during_measurement_cannot_publish_old_provenance(
    tmp_path, monkeypatch
):
    mod = metric_module()
    package = sources(tmp_path, "def work(x):\n    return x\n")
    profile = coverage(tmp_path, {"work": function(1, [2], [])})
    original = mod._coupling

    def changed(source):
        result = original(source)
        (package / "logic.py").write_text(
            "def work(x):\n    return x + 1\n", encoding="utf-8"
        )
        return result

    monkeypatch.setattr(mod, "_coupling", changed)
    with pytest.raises(ValueError, match="source changed during"):
        report(mod, tmp_path, profile)


@pytest.mark.parametrize(
    "problem", ("start", "counts", "ownership", "path", "identity")
)
def test_invalid_or_stale_function_evidence_is_unmeasured(tmp_path, problem):
    sources(tmp_path, "def work(x):\n    return x\n")
    region = function(1, [2], [])
    filename = "src/avo/logic.py"
    provenance = None
    if problem == "start":
        region["start_line"] = 9
    elif problem == "counts":
        region["summary"]["covered_lines"] = 7
    elif problem == "ownership":
        region["executed_lines"] = [1]
    elif problem == "path":
        filename = "../other/src/avo/logic.py"
    else:
        provenance = {"sha": "b" * 40, "run_id": RUN_ID}
    document = report(
        metric_module(),
        tmp_path,
        coverage(tmp_path, {"work": region}, filename=filename, provenance=provenance),
    )
    assert document["functions"][0]["crap"]["value"] is None
    assert document["summary"]["unmeasured_functions"] == 1


def test_receipt_hash_identity_and_source_fingerprint_are_required_when_supplied(
    tmp_path,
):
    mod = metric_module()
    sources(tmp_path, "def work(x):\n    return x\n")
    profile = coverage(tmp_path, {"work": function(1, [2], [])})
    local = report(mod, tmp_path, profile)
    receipt = tmp_path / "receipt.json"
    payload = {
        "schema_version": 1,
        "gate": "coverage",
        "sha": SHA,
        "run_id": RUN_ID,
        "status": "PASS",
        "exit_code": 0,
        "artifacts": [
            {
                "path": "reports/quality/coverage.json",
                "sha256": local["provenance"]["coverage"]["sha256"],
                "reason": None,
            }
        ],
        "source": {
            "unchanged": True,
            "start": {"sha256": local["provenance"]["sources"]["sha256"]},
            "end": {"sha256": local["provenance"]["sources"]["sha256"]},
        },
    }
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    verified = report(
        mod, tmp_path, profile, coverage_receipt=receipt, require_receipt=True
    )
    assert verified["provenance"]["coverage"]["binding"] == "validated receipt"
    assert verified["summary"]["measured_functions"] == 1
    for key in ("sha", "run_id", "artifacts", "source", "status", "exit_code"):
        broken = {**payload, key: "invalid"}
        receipt.write_text(json.dumps(broken), encoding="utf-8")
        assert (
            report(mod, tmp_path, profile, coverage_receipt=receipt)["summary"][
                "max_crap"
            ]
            is None
        )
    missing = report(mod, tmp_path, profile, require_receipt=True)
    assert missing["summary"]["max_crap"] is None
    payload["source"]["unchanged"] = False
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        report(mod, tmp_path, profile, coverage_receipt=receipt)["summary"]["max_crap"]
        is None
    )
    payload["source"]["unchanged"] = True
    (tmp_path / "src" / "avo" / "logic.py").write_text(
        "def work(x):\n    if x:\n        return x\n    return 0\n", encoding="utf-8"
    )
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    changed = report(mod, tmp_path, profile, coverage_receipt=receipt)
    assert changed["summary"]["max_crap"] is None
    assert "source fingerprint mismatch" in changed["provenance"]["coverage"]["reason"]


@pytest.mark.parametrize("test_outcome", ("unknown", "failure", "skipped", "cancelled"))
def test_unsuccessful_suite_keeps_crap_unavailable(tmp_path, test_outcome):
    sources(tmp_path, "def work(x):\n    return x\n")
    profile = coverage(tmp_path, {"work": function(1, [2], [])})
    document = report(metric_module(), tmp_path, profile, test_outcome=test_outcome)
    assert document["summary"]["max_complexity"] == 1
    assert document["summary"]["max_crap"] is None
    assert document["provenance"]["coverage"]["test_outcome"] == test_outcome


def test_real_branch_instrumented_coverage_uses_statement_ratio(tmp_path):
    package = sources(
        tmp_path, "def gate(x):\n    if x:\n        return x\n    return 0\n"
    )
    path = package / "logic.py"
    profile = tmp_path / "coverage.json"
    # A separate process keeps ambient coverage tracers and relative-path settings
    # from other tests out of this actual-tool contract fixture.
    code = """
import runpy
import sys
from coverage import Coverage

run = Coverage(data_file=None, config_file=False, include=[sys.argv[1]], branch=True)
run.start()
try:
    namespace = runpy.run_path(sys.argv[1])
    namespace["gate"](1)
finally:
    run.stop()
run.json_report(outfile=sys.argv[2])
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path), str(profile)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    document = report(metric_module(), tmp_path, profile)
    row = document["functions"][0]
    assert row["function_coverage"]["percent"] == pytest.approx(100 * 2 / 3), row
    assert row["crap"]["value"] == pytest.approx(2 + 4 * (1 / 3) ** 3)


def test_coupling_reuses_package_graph_and_hashes_topology(tmp_path):
    mod = metric_module()
    package = sources(tmp_path, "def work():\n    return 1\n")
    (package / "alpha").mkdir()
    (package / "beta").mkdir()
    (package / "alpha" / "__init__.py").write_text(
        "from avo.beta import value\n", encoding="utf-8"
    )
    (package / "beta" / "__init__.py").write_text("value = 1\n", encoding="utf-8")
    coupling = report(mod, tmp_path, tmp_path / "missing.json")["coupling"]
    packages = {row["package"]: row for row in coupling["packages"]}
    assert packages["avo.alpha"] == {
        "package": "avo.alpha",
        "ca": 0,
        "ce": 1,
        "instability": 1.0,
    }
    assert packages["avo.beta"] == {
        "package": "avo.beta",
        "ca": 1,
        "ce": 0,
        "instability": 0.0,
    }
    assert packages["avo"]["instability"] is None
    assert coupling["edge_count"] == 1
    assert len(coupling["topology_sha256"]) == 64


def test_module_coupling_has_exact_file_namespace_and_topology_evidence(tmp_path):
    mod = metric_module()
    package = sources(tmp_path, "")
    files = {
        "group/__init__.py": "TOKEN = 1\n",
        "group/reader.py": (
            "import avo.group.target as alias\n"
            "from . import target\n"
            "from .target import VALUE\n"
            "import avo.group.reader\n"
            "import avo\n"
            "import avo.namespace\n"
        ),
        "group/target.py": "VALUE = 1\n",
        "group/isolated.py": "",
        "namespace/helper.py": "",
    }
    for name, text in files.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    document = report(mod, tmp_path, tmp_path / "missing.json")
    graph = document["coupling_modules"]
    assert graph["schema"] == 1
    assert graph["status"] == "MEASURED"
    assert graph["scope"] == "src/avo/**/*.py"
    rows = {row["module"]: row for row in graph["modules"]}
    assert list(rows) == sorted(rows)
    assert set(rows) == {
        "avo",
        "avo.logic",
        "avo.group",
        "avo.group.reader",
        "avo.group.target",
        "avo.group.isolated",
        "avo.namespace",
        "avo.namespace.helper",
    }
    assert graph["node_count"] == 8
    assert graph["edge_count"] == 3
    assert graph["edges"] == [
        ["avo.group.reader", "avo"],
        ["avo.group.reader", "avo.group.target"],
        ["avo.group.reader", "avo.namespace"],
    ]
    assert rows["avo.namespace"] == {
        "module": "avo.namespace",
        "kind": "namespace",
        "path": None,
        "sha256": None,
        "ca": 1,
        "ce": 0,
        "instability": 0.0,
    }
    manifest = {
        row["path"]: row["sha256"] for row in document["provenance"]["sources"]["files"]
    }
    actual_files = [row for row in graph["modules"] if row["kind"] == "file"]
    assert {row["path"] for row in actual_files} == set(manifest)
    for row in actual_files:
        assert row["sha256"] == manifest[row["path"]]
        assert (
            row["sha256"]
            == hashlib.sha256((tmp_path / row["path"]).read_bytes()).hexdigest()
        )
    assert rows["avo.group"]["path"] == "src/avo/group/__init__.py"
    assert rows["avo.group.reader"]["ca"] == 0
    assert rows["avo.group.reader"]["ce"] == 3
    assert rows["avo.group.reader"]["instability"] == 1.0
    assert rows["avo.group.target"]["ca"] == 1
    assert rows["avo.group.isolated"]["instability"] is None
    topology = {"nodes": sorted(rows), "edges": graph["edges"]}
    expected_hash = hashlib.sha256(
        json.dumps(topology, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert graph["topology_sha256"] == expected_hash
    assert document["coupling"] == mod._coupling(package)
    assert graph == report(mod, tmp_path, tmp_path / "missing.json")["coupling_modules"]


@pytest.mark.parametrize(
    ("extra_files", "reason"),
    [
        ({"bad.py": "def broken(:"}, "bad.py"),
        ({"bad.py": "import avo.missing\n"}, "avo.missing"),
        ({"group.py": "", "group/__init__.py": ""}, "ambiguous"),
    ],
)
def test_failed_module_coupling_is_unavailable_not_an_empty_measurement(
    tmp_path, extra_files, reason
):
    package = sources(tmp_path, "")
    for name, text in extra_files.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    graph = report(metric_module(), tmp_path, tmp_path / "missing.json")[
        "coupling_modules"
    ]
    assert graph["status"] == "UNAVAILABLE"
    assert graph["modules"] == [] and graph["edges"] == []
    assert graph["node_count"] is None and graph["edge_count"] is None
    assert graph["topology_sha256"] is None
    assert reason in graph["reason"]


def test_module_measurement_preserves_unreferenced_namespace_identity(tmp_path):
    package = tmp_path / "src" / "avo"
    path = package / "nested" / "isolated.py"
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    graph = report(metric_module(), tmp_path, tmp_path / "missing.json")[
        "coupling_modules"
    ]
    rows = {row["module"]: row for row in graph["modules"]}
    assert graph["status"] == "MEASURED"
    assert graph["node_count"] == 3 and graph["edge_count"] == 0
    for module in ("avo", "avo.nested"):
        assert rows[module]["kind"] == "namespace"
        assert rows[module]["path"] is None and rows[module]["sha256"] is None
    assert rows["avo.nested.isolated"]["kind"] == "file"
    assert all(row["instability"] is None for row in rows.values())


def test_source_change_during_module_measurement_rejects_the_report(
    tmp_path, monkeypatch
):
    mod = metric_module()
    package = sources(tmp_path, "def work():\n    return 1\n")
    original = mod._module_coupling

    def changed(source, manifest):
        result = original(source, manifest)
        (package / "logic.py").write_text(
            "def work():\n    return 2\n", encoding="utf-8"
        )
        return result

    monkeypatch.setattr(mod, "_module_coupling", changed)
    with pytest.raises(ValueError, match="source changed during"):
        report(mod, tmp_path, tmp_path / "missing.json")
