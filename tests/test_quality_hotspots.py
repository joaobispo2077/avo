"""Ranked views keep same-function values, identity and partial-population limits."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def helper():
    spec = importlib.util.spec_from_file_location(
        "quality_hotspots_test", ROOT / "scripts/ci/quality_hotspots.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def function(path, line, cc, crap, *, name="run"):
    return {
        "id": f"{path}:{line}:{name}",
        "module": "avo.example",
        "qualname": name,
        "path": path,
        "line": line,
        "end_line": line + 4,
        "source_sha256": "b" * 64,
        "complexity": cc,
        "function_coverage": {
            "status": "MEASURED" if crap is not None else "UNAVAILABLE",
            "covered_lines": 2 if crap is not None else None,
            "num_statements": 4 if crap is not None else None,
            "percent": 50 if crap is not None else None,
            "reason": "Validated same-function coverage."
            if crap is not None
            else "No measured function region.",
        },
        "crap": {
            "status": "MEASURED" if crap is not None else "UNAVAILABLE",
            "value": crap,
            "reference": 30,
            "informational": True,
            "reason": "Same-function evidence."
            if crap is not None
            else "Missing function coverage.",
        },
    }


def document():
    # Independently known at 50% function coverage: CC + CC²/8.
    records = [
        function("src/avo/z.py", 10, 8, 16),
        function("src/avo/a.py", 20, 8, 16),
        function("src/avo/a.py", 10, 4, 6),
        function("src/avo/b.py", 5, 12, None),
    ]
    return {
        "sha": SHA,
        "run_id": "42",
        "repository": "owner/avo",
        "reporting": {"schema": 1, "mode": "fixture"},
        "measurement_evidence": {
            "supporting": {
                "schema": 1,
                "source_fingerprint": "c" * 64,
                "sources": [{"path": "code-risk.json", "sha256": "d" * 64}],
                "functions": {
                    "state": "PARTIAL",
                    "reason": "One observed function has no coverage.",
                    "records": records,
                    "observed_functions": 4,
                    "measured_crap_functions": 3,
                    "unmeasured_observed_functions": 1,
                    "source_errors": [],
                    "total_population_known": True,
                },
            }
        },
    }


def test_stable_function_identity_precedes_separate_rankings():
    doc = document()
    original = copy.deepcopy(doc)
    series = helper().build_hotspot_series(doc)
    assert doc == original
    assert [(row["id"], row["path"], row["line"]) for row in series["functions"]] == [
        ("U0001", "src/avo/a.py", 10),
        ("U0002", "src/avo/a.py", 20),
        ("U0003", "src/avo/b.py", 5),
        ("U0004", "src/avo/z.py", 10),
    ]
    assert series["rankings"]["complexity"]["ids"] == [
        "U0003",
        "U0002",
        "U0004",
        "U0001",
    ]
    assert series["rankings"]["crap"]["ids"] == ["U0002", "U0004", "U0001"]
    assert series["rankings"]["crap"]["maximum"] == 16
    assert series["rankings"]["complexity"]["maximum"] == 12
    assert series["crap_reference"] == {"value": 30, "role": "informational"}


def test_partial_and_unknown_population_never_fabricate_missing_functions():
    doc = document()
    data = doc["measurement_evidence"]["supporting"]["functions"]
    data.update(
        source_errors=[{"path": "src/avo/broken.py", "reason": "Parse failure."}],
        total_population_known=False,
    )
    series = helper().build_hotspot_series(doc)
    assert series["state"] == "PARTIAL"
    assert series["population"]["observed_functions"] == 4
    assert series["population"]["measured_crap_functions"] == 3
    assert series["population"]["unmeasured_observed_functions"] == 1
    assert series["population"]["total_population_known"] is False
    assert series["population"]["source_error_count"] == 1
    assert series["functions"][2]["crap"]["value"] is None


def test_top_ten_cap_and_ties_leave_full_rows_available():
    doc = document()
    data = doc["measurement_evidence"]["supporting"]["functions"]
    data["records"] = [
        function("src/avo/a.py", index, 4, 6, name=f"run{index}")
        for index in reversed(range(1, 13))
    ]
    data.update(
        observed_functions=12,
        measured_crap_functions=12,
        unmeasured_observed_functions=0,
        state="MEASURED",
    )
    series = helper().build_hotspot_series(doc)
    assert len(series["functions"]) == 12
    for key in ("complexity", "crap"):
        ranking = series["rankings"][key]
        assert ranking["ids"] == [f"U{index:04}" for index in range(1, 11)]
        assert (ranking["shown"], ranking["eligible"], ranking["observed"]) == (
            10,
            12,
            12,
        )
        assert "path" in ranking["tie_rule"] and "line" in ranking["tie_rule"]


def test_input_order_does_not_change_series():
    doc = document()
    expected = helper().build_hotspot_series(doc)
    doc["measurement_evidence"]["supporting"]["functions"]["records"].reverse()
    assert helper().build_hotspot_series(doc) == expected


def test_raw_diagnostics_are_not_an_alternate_trust_path():
    doc = {
        "measurement_evidence": {
            "diagnostics": {
                "code_risk": {"functions": [function("src/avo/a.py", 1, 2, 2.5)]}
            }
        }
    }
    series = helper().build_hotspot_series(doc)
    assert series["state"] == "UNAVAILABLE" and series["functions"] == []
    assert series["rankings"]["complexity"]["maximum"] is None


def test_definition_identity_matches_the_normalized_snapshot():
    doc = document()
    doc["metric_definitions"] = {
        "schema": 1,
        "entries": [{"id": "crap"}],
        "catalog_sha256": "1" * 64,
        "policy_sha256": "2" * 64,
    }
    series = helper().build_hotspot_series(doc)
    assert series["definition_identity"] == {
        "catalog_sha256": "1" * 64,
        "policy_sha256": "2" * 64,
    }
    assert "metric_definitions" not in series


def test_no_crap_population_still_preserves_measured_complexity():
    doc = document()
    data = doc["measurement_evidence"]["supporting"]["functions"]
    data["records"] = [function("src/avo/a.py", 1, 4, None)]
    data.update(
        observed_functions=1, measured_crap_functions=0, unmeasured_observed_functions=1
    )
    series = helper().build_hotspot_series(doc)
    assert series["rankings"]["complexity"]["maximum"] == 4
    assert series["rankings"]["crap"]["ids"] == []
    assert series["rankings"]["crap"]["maximum"] is None


def test_indexes_preserve_every_observed_function_and_missing_inputs(tmp_path):
    mod = helper()
    series = mod.build_hotspot_series(document())
    paths = mod.write_hotspot_indexes(series, tmp_path)
    assert paths["json"].name == "hotspots.json"
    assert json.loads(paths["json"].read_text(encoding="utf-8")) == series
    text = paths["markdown"].read_text(encoding="utf-8")
    assert all(row["id"] in text and row["path"] in text for row in series["functions"])
    assert "Missing function coverage." in text and "informational" in text.lower()
    assert "2/4" in text and "50.00%" in text


def test_source_identity_is_escaped_and_ci_links_pin_definition_line(tmp_path):
    doc = document()
    doc["reporting"]["mode"] = "ci"
    doc["measurement_evidence"]["supporting"]["functions"]["records"][0]["qualname"] = (
        "odd|<script>`name`"
    )
    series = helper().build_hotspot_series(doc)
    assert (
        series["functions"][0]["source_url"]
        == f"https://github.com/owner/avo/blob/{SHA}/src/avo/a.py#L10"
    )
    text = (
        helper()
        .write_hotspot_indexes(series, tmp_path)["markdown"]
        .read_text(encoding="utf-8")
    )
    assert "<script>" not in text and "&lt;script&gt;" in text and "\\|" in text
    doc["reporting"]["mode"] = "fixture"
    assert all(
        row["source_url"] is None
        for row in helper().build_hotspot_series(doc)["functions"]
    )


def test_png_embeds_exact_series_including_partial_population(tmp_path):
    from PIL import Image

    mod = helper()
    series = mod.build_hotspot_series(document())
    path = tmp_path / "hotspots.png"
    mod.render_hotspots(series, path)
    with Image.open(path) as image:
        assert json.loads(image.info["Description"]) == series
        assert image.width >= 1000 and image.height >= 650


def test_unavailable_render_removes_stale_role_file(tmp_path):
    mod = helper()
    path = tmp_path / "hotspots.png"
    path.write_bytes(b"old image")
    with pytest.raises(ValueError, match="unavailable"):
        mod.render_hotspots(mod.build_hotspot_series({}), path)
    assert not path.exists()


def test_failed_render_leaves_complete_current_text_but_no_partial_png(
    tmp_path, monkeypatch
):
    from matplotlib.figure import Figure

    mod = helper()
    series = mod.build_hotspot_series(document())
    outputs = mod.write_hotspot_indexes(series, tmp_path)
    path = tmp_path / "hotspots.png"

    def fail_save(_figure, target, **_kwargs):
        Path(target).write_bytes(b"partial PNG")
        raise OSError("Image failed.")

    monkeypatch.setattr(Figure, "savefig", fail_save)
    with pytest.raises(OSError, match="Image failed"):
        mod.render_hotspots(series, path)
    assert not path.exists()
    assert json.loads(outputs["json"].read_text(encoding="utf-8")) == series
    assert "U0004" in outputs["markdown"].read_text(encoding="utf-8")


def test_long_display_labels_keep_full_identity_in_the_text_index(
    tmp_path, monkeypatch
):
    import matplotlib.pyplot as plt

    doc = document()
    original = doc["measurement_evidence"]["supporting"]["functions"]["records"][0]
    original["path"] = "src/avo/" + "long_filename_" * 8 + ".py"
    original["qualname"] = "VeryLongClass." + "long_method_" * 8
    mod = helper()
    series = mod.build_hotspot_series(doc)
    indexes = mod.write_hotspot_indexes(series, tmp_path)
    figures = []
    close = plt.close
    monkeypatch.setattr(plt, "close", figures.append)
    mod.render_hotspots(series, tmp_path / "long-labels.png")
    labels = [
        label.get_text() for ax in figures[-1].axes for label in ax.get_yticklabels()
    ]
    assert any("…" in label for label in labels)
    text = indexes["markdown"].read_text(encoding="utf-8")
    assert original["path"] in text and original["qualname"] in text
    close(figures[-1])
