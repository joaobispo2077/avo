"""File positions remain recoverable through the same frozen plot and text data."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from random import Random

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def helper():
    spec = importlib.util.spec_from_file_location(
        "quality_coupling_test", ROOT / "scripts/ci/coupling_dashboard.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def document():
    # a imports b, d and ns; b, d and e import a. c is isolated.
    degrees = [("a", 3, 3), ("b", 1, 1), ("c", 0, 0), ("d", 1, 1), ("ns/e", 0, 1)]
    nodes = [
        {
            "module": f"avo.{name.replace('/', '.')}",
            "path": f"src/avo/{name}.py",
            "sha256": "b" * 64,
            "kind": "file",
            "ca": ca,
            "ce": ce,
            "instability": ce / (ca + ce) if ca + ce else None,
        }
        for name, ca, ce in degrees
    ]
    nodes.append(
        {
            "module": "avo.ns",
            "path": None,
            "sha256": None,
            "kind": "namespace",
            "ca": 1,
            "ce": 0,
            "instability": 0.0,
        }
    )
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
                "coupling": {
                    "state": "MEASURED",
                    "reason": "Verified static internal imports.",
                    "modules": nodes,
                    "edges": [
                        ["avo.a", "avo.b"],
                        ["avo.a", "avo.d"],
                        ["avo.a", "avo.ns"],
                        ["avo.b", "avo.a"],
                        ["avo.d", "avo.a"],
                        ["avo.ns.e", "avo.a"],
                    ],
                    "node_count": 6,
                    "edge_count": 6,
                    "topology_sha256": "e" * 64,
                },
            }
        },
    }


def test_exact_group_membership_and_path_sorted_file_identity():
    doc = document()
    original = copy.deepcopy(doc)
    series = helper().build_coupling_series(doc)
    assert doc == original
    assert [(row["id"], row["path"]) for row in series["files"]] == [
        (f"F{index:03}", f"src/avo/{name}.py")
        for index, name in enumerate(["a", "b", "c", "d", "ns/e"], 1)
    ]
    assert [(g["id"], g["ce"], g["ca"], g["file_ids"]) for g in series["groups"]] == [
        ("G01", 0, 0, ["F003"]),
        ("G02", 1, 0, ["F005"]),
        ("G03", 1, 1, ["F002", "F004"]),
        ("G04", 3, 3, ["F001"]),
    ]
    assert series["groups"][2]["member_count"] == 2
    assert series["file_count"] == 5 and series["namespace_count"] == 1
    assert series["files"][2]["instability"] is None
    assert series["source_fingerprint"] == "c" * 64


def test_medians_include_isolates_and_equality_stays_lower():
    series = helper().build_coupling_series(document())
    assert series["references"]["ce"] == 1
    assert series["references"]["ca"] == 1
    assert (
        series["references"]["population"]
        == "all measured actual files, including isolates"
    )
    assert series["references"]["equality"] == "lower"
    assert series["files"][1]["region"] == "few_connections"
    assert series["files"][0]["region"] == "high_connectivity"
    assert series["axes"]["x"] == "ce" and series["axes"]["y"] == "ca"
    assert series["axes"] == {
        "x": "ce",
        "y": "ca",
        "transform": "piecewise log2(1 + count) around raw median",
        "ticks": "raw counts",
        "quadrants": "equal display area",
        "median_position": 0.5,
        "zero_median": "zero at division; lower numeric range empty",
        "equality": "lower",
    }


def test_input_order_never_renumbers_identical_snapshot():
    doc = document()
    expected = helper().build_coupling_series(doc)
    doc["measurement_evidence"]["supporting"]["coupling"]["modules"].reverse()
    assert helper().build_coupling_series(doc) == expected


def test_package_only_or_unavailable_graph_supplies_no_file_positions():
    mod = helper()
    doc = document()
    doc["measurement_evidence"] = {
        "diagnostics": {"code_risk": {"coupling": {"packages": [{"ca": 9, "ce": 9}]}}}
    }
    series = mod.build_coupling_series(doc)
    assert series["state"] == "UNAVAILABLE"
    assert series["files"] == series["groups"] == []
    doc = document()
    doc["measurement_evidence"]["supporting"]["coupling"].update(
        state="UNAVAILABLE", reason="Source receipt mismatch."
    )
    series = mod.build_coupling_series(doc)
    assert series["files"] == [] and "receipt mismatch" in series["reason"]


def test_empty_population_does_not_invent_zero_medians():
    doc = document()
    doc["measurement_evidence"]["supporting"]["coupling"]["modules"] = []
    series = helper().build_coupling_series(doc)
    assert series["state"] == "UNAVAILABLE"
    assert series["references"]["ca"] is None and series["references"]["ce"] is None


def test_measured_isolates_retain_zero_medians_and_one_complete_group():
    doc = document()
    graph = doc["measurement_evidence"]["supporting"]["coupling"]
    graph["modules"] = graph["modules"][:3]
    for node in graph["modules"]:
        node.update(ca=0, ce=0, instability=None)
    graph.update(edges=[], node_count=3, edge_count=0)
    series = helper().build_coupling_series(doc)
    assert series["state"] == "MEASURED"
    assert series["references"]["ca"] == series["references"]["ce"] == 0
    assert series["groups"] == [
        {
            "id": "G01",
            "ce": 0,
            "ca": 0,
            "file_ids": ["F001", "F002", "F003"],
            "member_count": 3,
            "region": "few_connections",
        }
    ]


def test_definition_identity_is_small_and_retains_both_digests():
    doc = document()
    doc["metric_definitions"] = {
        "schema": 1,
        "entries": [{"id": "coupling_files"}],
        "catalog_sha256": "1" * 64,
        "policy_sha256": "2" * 64,
    }
    series = helper().build_coupling_series(doc)
    assert series["definition_identity"] == {
        "catalog_sha256": "1" * 64,
        "policy_sha256": "2" * 64,
    }
    assert "metric_definitions" not in series


@pytest.mark.parametrize("mode", ["fixture", "local-preview", None])
def test_fixture_local_and_legacy_context_do_not_fabricate_commit_links(mode):
    doc = document()
    doc["reporting"]["mode"] = mode
    assert all(
        row["source_url"] is None
        for row in helper().build_coupling_series(doc)["files"]
    )


def test_ci_source_links_are_safe_and_commit_bound():
    doc = document()
    doc["reporting"]["mode"] = "ci"
    rows = helper().build_coupling_series(doc)["files"]
    assert (
        rows[0]["source_url"] == f"https://github.com/owner/avo/blob/{SHA}/src/avo/a.py"
    )
    doc["repository"] = "owner/avo?redirect=evil"
    assert all(
        row["source_url"] is None
        for row in helper().build_coupling_series(doc)["files"]
    )


def test_indexes_account_for_every_member_and_preserve_exact_series(tmp_path):
    mod = helper()
    series = mod.build_coupling_series(document())
    outputs = mod.write_coupling_indexes(series, tmp_path)
    assert outputs["json"].name == "coupling-index.json"
    assert json.loads(outputs["json"].read_text(encoding="utf-8")) == series
    text = outputs["markdown"].read_text(encoding="utf-8")
    assert "G03" in text and "F002" in text and "F004" in text
    assert all(f"src/avo/{name}.py" in text for name in ["a", "b", "c", "d", "ns/e"])
    assert "log2(1 + count)" in text and "informational" in text.lower()
    assert "namespace" in text.lower() and "including isolates" in text


def test_markdown_escapes_source_markup_without_losing_identity(tmp_path):
    doc = document()
    node = doc["measurement_evidence"]["supporting"]["coupling"]["modules"][0]
    node["module"] = "avo.<script>|`x`"
    series = helper().build_coupling_series(doc)
    text = (
        helper()
        .write_coupling_indexes(series, tmp_path)["markdown"]
        .read_text(encoding="utf-8")
    )
    assert "<script>" not in text
    assert "&lt;script&gt;" in text and "\\|" in text
    assert series["files"][0]["module"] == "avo.<script>|`x`"


def test_png_contains_the_exact_frozen_series(tmp_path):
    from PIL import Image

    mod = helper()
    series = mod.build_coupling_series(document())
    image_path = tmp_path / "coupling-files.png"
    mod.render_coupling(series, image_path)
    with Image.open(image_path) as image:
        assert json.loads(image.info["Description"]) == series
        assert image.width >= 1000 and image.height >= 650


def test_unavailable_render_refuses_to_leave_a_stale_image(tmp_path):
    mod = helper()
    series = mod.build_coupling_series({})
    path = tmp_path / "coupling-files.png"
    path.write_bytes(b"stale")
    with pytest.raises(ValueError, match="unavailable"):
        mod.render_coupling(series, path)
    assert not path.exists()


def test_old_axis_metadata_cannot_claim_to_describe_new_spacing(tmp_path):
    mod = helper()
    series = mod.build_coupling_series(document())
    series["axes"]["transform"] = "log2(1 + count)"
    path = tmp_path / "coupling-files.png"
    path.write_bytes(b"old image")
    with pytest.raises(ValueError, match="axis metadata"):
        mod.render_coupling(series, path)
    assert not path.exists()


@pytest.mark.parametrize(
    ("maximum", "expected"),
    [
        (0, [0]),
        (8, [0, 1, 3, 8]),
        (12, [0, 1, 3, 7, 12]),
        (63, [0, 1, 3, 7, 15, 31, 63]),
        (67, [0, 1, 3, 7, 15, 31, 67]),
    ],
)
def test_terminal_ticks_do_not_put_nearby_labels_on_top_of_one_another(
    maximum, expected
):
    assert helper()._ticks(maximum) == expected


@pytest.mark.parametrize(
    ("mode", "prefix"),
    [
        ("local-preview", "Working-tree preview"),
        ("fixture", "Fixture source reference"),
        ("ci", "Commit"),
    ],
)
def test_image_header_describes_the_actual_source_context(
    tmp_path, monkeypatch, mode, prefix
):
    import matplotlib.pyplot as plt

    doc = document()
    doc["reporting"]["mode"] = mode
    mod = helper()
    series = mod.build_coupling_series(doc)
    figures = []
    close = plt.close
    monkeypatch.setattr(plt, "close", figures.append)
    mod.render_coupling(series, tmp_path / "source-context.png")
    texts = [text.get_text() for text in figures[-1].texts]
    header = next(text for text in texts if text.startswith(prefix))
    assert "Run 42" in header
    if mode == "local-preview":
        assert "HEAD reference" in header and SHA[:10] in header
        assert "source " + "c" * 10 in header
        assert not any(text.startswith("Commit ") for text in texts)
    elif mode == "fixture":
        assert "c" * 10 in header
        assert not any(text.startswith("Commit ") for text in texts)
    else:
        assert SHA[:10] in header
    close(figures[-1])


def test_failed_render_keeps_current_indexes_and_removes_partial_png(
    tmp_path, monkeypatch
):
    from matplotlib.figure import Figure

    mod = helper()
    series = mod.build_coupling_series(document())
    outputs = mod.write_coupling_indexes(series, tmp_path)
    path = tmp_path / "coupling-files.png"

    def fail_save(_figure, target, **_kwargs):
        Path(target).write_bytes(b"partial PNG")
        raise OSError("No space for image.")

    monkeypatch.setattr(Figure, "savefig", fail_save)
    with pytest.raises(OSError, match="No space"):
        mod.render_coupling(series, path)
    assert not path.exists()
    assert json.loads(outputs["json"].read_text(encoding="utf-8")) == series
    assert "F005" in outputs["markdown"].read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("count", "reference", "maximum", "expected"),
    [
        (0, 3, 15, 0),
        (1, 3, 15, 0.25),
        (3, 3, 15, 0.5),
        (7, 3, 15, 0.75),
        (15, 3, 15, 1),
        (0, 0, 7, 0.5),
        (1, 0, 7, 2 / 3),
        (0, 0, 0, 0.5),
        (3, 3, 3, 0.5),
    ],
)
def test_equal_area_mapping_preserves_raw_median_and_discloses_empty_halves(
    count, reference, maximum, expected
):
    assert helper().axis_position(count, reference, maximum) == pytest.approx(expected)


def test_reference_layout_has_numbered_exact_dots_and_complete_below_plot_index(
    tmp_path, monkeypatch
):
    import matplotlib.pyplot as plt

    doc = document()
    random = Random(17)
    names = [f"avo.file{index:03}" for index in range(45)]
    edges = sorted(
        {
            (origin, target)
            for index, origin in enumerate(names)
            for target in random.sample(
                [name for name in names if name != origin], index % 14
            )
        }
    )
    nodes = []
    for index, name in enumerate(names):
        ca = sum(target == name for _, target in edges)
        ce = sum(origin == name for origin, _ in edges)
        nodes.append(
            {
                "module": name,
                "kind": "file",
                "path": f"src/avo/file{index:03}.py",
                "sha256": "b" * 64,
                "ca": ca,
                "ce": ce,
                "instability": ce / (ca + ce) if ca + ce else None,
            }
        )
    graph = doc["measurement_evidence"]["supporting"]["coupling"]
    graph.update(modules=nodes, edges=edges, node_count=45, edge_count=len(edges))
    mod = helper()
    series = mod.build_coupling_series(doc)
    expected = copy.deepcopy(series)
    figures = []
    close = plt.close
    monkeypatch.setattr(plt, "close", figures.append)
    mod.render_coupling(series, tmp_path / "crowded.png")
    figure = figures[-1]
    axis = figure.axes[0]
    labels = [text for text in axis.texts if text.get_text().isdigit()]
    assert {text.get_text() for text in labels} == {
        str(index) for index in range(1, len(series["groups"]) + 1)
    }
    assert len(labels) == len(series["groups"])
    for marker, group in zip(axis.collections, series["groups"], strict=True):
        assert tuple(marker.get_offsets()[0]) == pytest.approx(
            (
                mod.axis_position(
                    group["ce"],
                    series["references"]["ce"],
                    max(g["ce"] for g in series["groups"]),
                ),
                mod.axis_position(
                    group["ca"],
                    series["references"]["ca"],
                    max(g["ca"] for g in series["groups"]),
                ),
            )
        )
    text = "\n".join(item.get_text() for item in figure.texts)
    for index, group in enumerate(series["groups"], 1):
        assert (
            f"{index:02}/{group['id']}  {group['ca']}/{group['ce']} ×{group['member_count']}"
            in text
        )
        first = next(
            row for row in series["files"] if row["id"] == group["file_ids"][0]
        )
        assert first["id"] in text and first["module"].removeprefix("avo.") in text
        if group["member_count"] > 1:
            assert f"+{group['member_count'] - 1}" in text
    width, height = figure.get_size_inches()
    bounds = axis.get_position()
    assert width * bounds.width / (height * bounds.height) == pytest.approx(2)
    assert "+N means other files" in text
    assert "not gates or architectural health" in text
    assert "independently scaled" in text
    # Four equal display rectangles retain the reference layout's color roles.
    from matplotlib.colors import to_hex

    assert [to_hex(patch.get_facecolor()) for patch in axis.patches[:4]] == [
        "#e4f0e6",
        "#f7e4e1",
        "#f6efd9",
        "#e4f0e6",
    ]
    assert all(
        patch.get_width() == pytest.approx(0.525)
        and patch.get_height() == pytest.approx(0.525)
        for patch in axis.patches[:4]
    )
    assert series == expected
    close(figure)


def test_only_colliding_numbers_receive_short_tethers_and_zero_range_is_disclosed(
    tmp_path, monkeypatch
):
    import matplotlib.pyplot as plt

    doc = document()
    names = ["avo.hub_a", "avo.hub_b"] + [f"avo.leaf{n:02}" for n in range(23)]
    edges = [
        (name, names[0] if n < 11 else names[1]) for n, name in enumerate(names[2:])
    ]
    nodes = []
    for name in names:
        ca = sum(target == name for _, target in edges)
        ce = sum(origin == name for origin, _ in edges)
        nodes.append(
            {
                "module": name,
                "kind": "file",
                "path": f"src/avo/{name[4:]}.py",
                "sha256": "b" * 64,
                "ca": ca,
                "ce": ce,
                "instability": ce / (ca + ce),
            }
        )
    doc["measurement_evidence"]["supporting"]["coupling"].update(
        modules=nodes, edges=edges, node_count=len(nodes), edge_count=len(edges)
    )
    mod = helper()
    series = mod.build_coupling_series(doc)
    figures = []
    close = plt.close
    monkeypatch.setattr(plt, "close", figures.append)
    mod.render_coupling(series, tmp_path / "nearby.png")
    figure = figures[-1]
    tethers = [text for text in figure.axes[0].texts if hasattr(text, "arrow_patch")]
    assert 0 < len(tethers) <= 2
    for text in tethers:
        assert max(abs(offset) for offset in text.xyann) <= 30
        group = series["groups"][int(text.get_text()) - 1]
        assert text.xy == pytest.approx(
            (
                mod.axis_position(group["ce"], 1, 1),
                mod.axis_position(group["ca"], 0, 12),
            )
        )
    captions = "\n".join(text.get_text() for text in figure.texts)
    assert "CA: zero at division; lower numeric range empty" in captions
    assert "CE: upper numeric range empty" in captions
    assert "colliding numbers use short tethers" in captions
    close(figure)
