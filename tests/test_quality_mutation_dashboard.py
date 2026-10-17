"""Mutation plots retain evidence, accounting and aggregate-only enforcement."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATUSES = (
    "killed",
    "survived",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
    "not_checked",
    "caught_by_type_check",
    "untested",
)


def helper():
    spec = importlib.util.spec_from_file_location(
        "test_mutation_view", ROOT / "scripts/ci/quality_mutation_dashboard.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def counts(killed, survived, timeout=0):
    return {
        **dict.fromkeys(STATUSES, 0),
        "killed": killed,
        "survived": survived,
        "timeout": timeout,
        "total": killed + survived + timeout,
        "unaccounted": 0,
    }


def scope(path, killed, survived, timeout=0):
    complete = not timeout and killed + survived > 0
    return {
        "path": path,
        "state": "MEASURED" if complete else "PARTIAL" if timeout else "UNAVAILABLE",
        "reason": "Complete test verdicts."
        if complete
        else "Timeout."
        if timeout
        else "Zero mutants.",
        "counts": counts(killed, survived, timeout),
        "complete": complete,
        "score": 100 * killed / (killed + survived) if complete else None,
        "unresolved": timeout,
        "source_sha256": "b" * 64,
        "metadata": {"path": path + ".meta", "sha256": "d" * 64},
        "mutants": [],
    }


def document():
    aggregate_source = {
        "artifact": "mutation-reports-light",
        "path": "mutation-metrics.json",
        "sha256": "e" * 64,
    }
    scopes_source = {
        "artifact": "mutation-reports-light",
        "path": "mutation-scopes.json",
        "sha256": "f" * 64,
    }
    return {
        "sha": "a" * 40,
        "run_id": "42",
        "repository": "owner/avo",
        "reporting": {"mode": "fixture"},
        "mutation_policy": {"profile": "light", "floor": 60},
        "mutation": {
            "sha": "a" * 40,
            "run_id": "42",
            "profile": "light",
            "floor": 60,
            "counts": counts(16, 4),
        },
        "metric_definitions": {"catalog_sha256": "1" * 64, "policy_sha256": "2" * 64},
        "measurement_evidence": {
            "schema": 1,
            "metrics": [
                {
                    "key": "mutation",
                    "state": "MEASURED",
                    "number": 80.0,
                    "unit": "percent",
                    "sources": [aggregate_source],
                }
            ],
            "supporting": {
                "sources": [{"artifact": "WRONG-GRAPH", "path": "code-risk.json"}],
                "source_fingerprint": "0" * 64,
            },
            "mutation_scopes": {
                "schema": 1,
                "state": "MEASURED",
                "reason": "Verified per-source outcomes.",
                "profile": "light",
                "threshold_scope": "aggregate",
                "sources": [scopes_source],
                "source_fingerprint": hashlib.sha256(
                    json.dumps(
                        [scopes_source], sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
                "scopes": [scope("src/avo/z.py", 1, 4), scope("src/avo/a.py", 15, 0)],
            },
        },
    }


def test_real_scope_scores_have_path_sorted_ids_and_no_local_gate():
    doc = document()
    original = copy.deepcopy(doc)
    series = helper().build_mutation_series(doc)
    assert doc == original
    assert [(r["id"], r["path"], r["score"]) for r in series["scopes"]] == [
        ("M001", "src/avo/a.py", 100),
        ("M002", "src/avo/z.py", 20),
    ]
    assert all(row["gate"] is None for row in series["scopes"])
    assert (
        series["aggregate"]["status"] == "PASS"
        and series["aggregate"]["measured"] == 80
    )
    assert series["policy"]["floor"] == 60 and series["policy"]["clear_percent"] == 70
    assert series["policy"]["threshold_scope"] == "aggregate"
    assert series["display"]["ids"] == ["M002", "M001"]
    assert series["state"] == "MEASURED"
    assert all(r["artifact"] != "WRONG-GRAPH" for r in series["sources"])
    assert series["definition_identity"] == {
        "catalog_sha256": "1" * 64,
        "policy_sha256": "2" * 64,
    }


def test_aggregate_only_legacy_data_stays_partial_without_invented_scopes():
    doc = document()
    del doc["measurement_evidence"]["mutation_scopes"]
    series = helper().build_mutation_series(doc)
    assert series["state"] == "PARTIAL" and series["scopes"] == []
    assert series["aggregate"]["measured"] == 80 and series["complete"]
    assert series["sources"] == doc["measurement_evidence"]["metrics"][0]["sources"]


@pytest.mark.parametrize("wrong", ["profile", "source_fingerprint"])
def test_wrong_scoped_profile_or_reference_fingerprint_does_not_supply_scores(wrong):
    doc = document()
    doc["measurement_evidence"]["mutation_scopes"][wrong] = (
        "full" if wrong == "profile" else "0" * 64
    )
    series = helper().build_mutation_series(doc)
    assert series["aggregate"]["measured"] == 80
    assert series["scopes"] == [] and series["state"] == "PARTIAL"
    assert series["sources"] == doc["measurement_evidence"]["metrics"][0]["sources"]


@pytest.mark.parametrize(
    "failure", ["missing_observation", "stale_run", "missing_sources", "wrong_score"]
)
def test_aggregate_needs_current_validated_observation_and_proof(failure):
    doc = document()
    if failure == "missing_observation":
        doc["measurement_evidence"]["metrics"] = []
    elif failure == "stale_run":
        doc["mutation"]["run_id"] = "41"
    elif failure == "missing_sources":
        doc["measurement_evidence"]["metrics"][0]["sources"] = []
    else:
        doc["measurement_evidence"]["metrics"][0]["number"] = 99
    series = helper().build_mutation_series(doc)
    assert series["aggregate"]["measured"] is None
    assert series["aggregate"]["status"] != "PASS"


def test_unresolved_zero_and_missing_scope_counts_are_distinct():
    doc = document()
    data = doc["measurement_evidence"]["mutation_scopes"]
    missing = scope("src/avo/missing.py", 0, 0)
    missing.update(
        counts=None, unresolved=None, metadata=None, reason="Metadata unavailable."
    )
    data.update(
        state="PARTIAL",
        scopes=[
            scope("src/avo/timeout.py", 1, 1, 1),
            scope("src/avo/zero.py", 0, 0),
            missing,
        ],
    )
    series = helper().build_mutation_series(doc)
    rows = {r["path"]: r for r in series["scopes"]}
    assert (
        rows["src/avo/timeout.py"]["score"] is None
        and rows["src/avo/timeout.py"]["unresolved"] == 1
    )
    assert (
        rows["src/avo/zero.py"]["counts"]["total"] == 0
        and rows["src/avo/zero.py"]["score"] is None
    )
    assert rows["src/avo/missing.py"]["counts"] is None
    assert series["state"] == "PARTIAL"


def test_scope_source_links_are_ci_only():
    mod = helper()
    doc = document()
    assert all(
        r["source_url"] is None for r in mod.build_mutation_series(doc)["scopes"]
    )
    doc["reporting"]["mode"] = "ci"
    assert (
        mod.build_mutation_series(doc)["scopes"][0]["source_url"]
        == f"https://github.com/owner/avo/blob/{'a' * 40}/src/avo/a.py"
    )


@pytest.mark.parametrize("values", [(0, 0, 0), (1, 1, 2)])
def test_verified_zero_or_timeout_accounting_keeps_no_successful_score(values):
    doc = document()
    doc["mutation"]["counts"] = counts(*values)
    doc["measurement_evidence"]["metrics"][0].update(state="UNAVAILABLE", number=None)
    doc["measurement_evidence"]["mutation_scopes"].update(
        state="PARTIAL", scopes=[scope("src/avo/a.py", *values)]
    )
    series = helper().build_mutation_series(doc)
    assert series["aggregate"]["status"] == "INCOMPLETE"
    assert series["aggregate"]["measured"] is None and not series["complete"]
    assert series["counts"]["total"] == sum(values)
    assert series["unresolved"] == values[2]
    assert series["state"] == "PARTIAL"


def test_frozen_validation_checks_arithmetic_even_if_document_row_is_bad():
    mod = helper()
    doc = document()
    doc["measurement_evidence"]["mutation_scopes"]["scopes"][0]["score"] = 100
    series = mod.build_mutation_series(doc)
    with pytest.raises(ValueError, match="accounting"):
        mod.validate_frozen_series(series, doc)


def test_frozen_reconciliation_accepts_an_upstream_omitted_status_bucket():
    mod = helper()
    doc = document()
    doc["mutation"]["counts"] = {"killed": 1, "survived": 0, "total": 2}
    doc["measurement_evidence"]["metrics"][0].update(state="UNAVAILABLE", number=None)
    row = scope("src/avo/a.py", 1, 0)
    row["counts"].update(not_checked=1, total=2)
    row.update(
        state="PARTIAL", complete=False, score=None, unresolved=1, reason="Not checked."
    )
    doc["measurement_evidence"]["mutation_scopes"].update(state="PARTIAL", scopes=[row])
    series = mod.build_mutation_series(doc)
    assert series["aggregate"]["measured"] is None and series["unresolved"] == 1
    assert mod.validate_frozen_series(series, doc) is True


def test_complete_indexes_and_png_keep_the_exact_frozen_series(tmp_path):
    from PIL import Image

    mod = helper()
    doc = document()
    series = mod.build_mutation_series(doc)
    outputs = mod.write_mutation_indexes(series, tmp_path)
    assert outputs["json"].name == "mutation-efficacy.json"
    assert json.loads(outputs["json"].read_text()) == series
    text = outputs["markdown"].read_text(encoding="utf-8")
    assert "src/avo/a.py" in text and "src/avo/z.py" in text and "60%" in text
    assert "20" in text and "informational" in text.lower()
    assert "mutation-scopes.json" in text and "mutation-metrics.json" in text
    mod.render_mutation(series, tmp_path / "mutation-efficacy.png")
    with Image.open(tmp_path / "mutation-efficacy.png") as image:
        assert json.loads(image.info["Description"]) == series
        assert image.width >= 1500
    assert mod.validate_frozen_series(series, doc) is True


@pytest.mark.parametrize("change", ["id", "score", "fingerprint", "aggregate"])
def test_frozen_validation_rejects_changed_id_score_binding_or_aggregate(change):
    mod = helper()
    doc = document()
    series = mod.build_mutation_series(doc)
    if change == "id":
        series["scopes"][0]["id"] = "M999"
    elif change == "score":
        series["scopes"][1]["score"] = 100
    elif change == "fingerprint":
        series["source_fingerprint"] = "0" * 64
    else:
        series["aggregate"]["measured"] = 100
    with pytest.raises(ValueError):
        mod.validate_frozen_series(series, doc)


def test_failed_save_removes_partial_image_but_leaves_indexes(tmp_path, monkeypatch):
    from matplotlib.figure import Figure

    mod = helper()
    series = mod.build_mutation_series(document())
    outputs = mod.write_mutation_indexes(series, tmp_path)
    path = tmp_path / "mutation-efficacy.png"

    def fail(_fig, target, **_kwargs):
        Path(target).write_bytes(b"partial")
        raise OSError("No space")

    monkeypatch.setattr(Figure, "savefig", fail)
    with pytest.raises(OSError):
        mod.render_mutation(series, path)
    assert not path.exists() and outputs["json"].exists()


def test_malformed_frozen_shape_raises_value_error():
    mod = helper()
    doc = document()
    series = mod.build_mutation_series(doc)
    del series["scopes"]
    with pytest.raises(ValueError):
        mod.validate_frozen_series(series, doc)


def test_dense_long_paths_are_bounded_and_full_lookup_survives(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt

    mod = helper()
    doc = document()
    data = doc["measurement_evidence"]["mutation_scopes"]
    data["scopes"] = [
        scope(f"src/avo/{'long_package_' * 8}/file{n:03}.py", 1, 1) for n in range(30)
    ]
    doc["mutation"]["counts"] = counts(30, 30)
    doc["measurement_evidence"]["metrics"][0]["number"] = 50
    series = mod.build_mutation_series(doc)
    figures = []
    close = plt.close
    monkeypatch.setattr(plt, "close", figures.append)
    mod.render_mutation(series, tmp_path / "dense.png")
    assert series["display"]["shown"] == 12 and series["display"]["total"] == 30
    text = mod.write_mutation_indexes(series, tmp_path)["markdown"].read_text(
        encoding="utf-8"
    )
    assert all(r["path"] in text for r in series["scopes"])
    figure = figures[-1]
    renderer = figure.canvas.get_renderer()
    assert all(
        t.get_window_extent(renderer).x1 <= figure.bbox.x1 + 1
        for ax in figure.axes
        for t in ax.texts
    )
    close(figure)
