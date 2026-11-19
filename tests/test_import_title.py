"""Imported title authorial data and font dependencies cannot masquerade as media."""

from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace

import pytest

from avo.timeline.import_layout import LayoutError, validate_layout
from avo.timeline.initial_cut_placed import _picture
from tests.test_timeline_import_layout import placed_snapshot, raw_time


def title_snapshot():
    snapshot = placed_snapshot()
    snapshot["sources"] = [
        {
            "sourceId": key,
            "kind": "authorial",
            "fingerprint": {"sha256": value * 64, "sizeBytes": 1},
        }
        for key, value in [("project", "a"), ("font", "b")]
    ]
    item = snapshot["layout"]["placements"][0]
    item.update(
        mediaKind="title",
        sourceId="project",
        routing={},
        fontSourceId="font",
        title={
            "text": "2026",
            "canvasWidth": 128,
            "canvasHeight": 96,
            "x": 64,
            "y": 48,
            "fontSize": 24,
            "color": "#FFFFFFFF",
            "anchor": "center",
        },
    )
    item["in"] = raw_time(0, "project")
    item["out"] = raw_time(24, "project")
    snapshot["layout"]["placements"] = [item]
    snapshot["layout"]["gaps"] = []
    return snapshot


def test_title_compiler_locks_authorial_and_font_sources(tmp_path):
    snapshot = title_snapshot()
    validate_layout(snapshot)
    sources = {
        s["sourceId"]: {**s, "locator": str(tmp_path / (s["sourceId"] + ".bin"))}
        for s in snapshot["sources"]
    }
    graph = _picture(
        snapshot,
        sources,
        {t["trackId"]: t for t in snapshot["layout"]["tracks"]},
        SimpleNamespace(raw_dir=tmp_path),
        Fraction(24),
        96,
    )
    operation = graph["operations"][0]
    item = operation["parameters"]["placements"][0]
    assert operation["inputs"] == ["font", "project"]
    assert item["title"] == snapshot["layout"]["placements"][0]["title"]
    assert item["fontSource"]["sourceId"] == "font"
    assert "streamIndex" not in item["source"]


@pytest.mark.parametrize(
    "defect",
    [
        "missing-font",
        "raw-font",
        "raw-project",
        "control-text",
        "unknown-field",
        "wrong-canvas",
    ],
)
def test_title_rejects_missing_dependencies_and_unsupported_text(defect):
    snapshot = deepcopy(title_snapshot())
    item = snapshot["layout"]["placements"][0]
    if defect == "missing-font":
        snapshot["sources"].pop()
    elif defect == "raw-font":
        snapshot["sources"][1]["kind"] = "raw"
    elif defect == "raw-project":
        snapshot["sources"][0]["kind"] = "raw"
    elif defect == "control-text":
        item["title"]["text"] = "hello\x00world"
    elif defect == "unknown-field":
        item["title"]["lua"] = "untrusted()"
    else:
        item["title"]["canvasWidth"] = 256
    with pytest.raises(LayoutError):
        validate_layout(snapshot)
