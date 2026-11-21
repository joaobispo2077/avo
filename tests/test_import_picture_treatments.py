"""Explicit bounded picture geometry and alpha fades stay canonical."""

from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace

import pytest

from avo.timeline.import_layout import LayoutError, validate_layout
from avo.timeline.initial_cut_placed import _picture
from tests.test_timeline_import_layout import placed_snapshot


def treated_snapshot():
    snapshot = placed_snapshot()
    item = snapshot["layout"]["placements"][0]
    item["pictureTransform"] = {
        "canvasWidth": 128,
        "canvasHeight": 96,
        "x": -12,
        "y": 8,
        "width": 64,
        "height": 48,
    }
    item["pictureFade"] = {"inFrames": 0, "outFrames": 6}
    return snapshot


def test_picture_operations_compile_as_exact_canonical_parameters(tmp_path):
    snapshot = treated_snapshot()
    validate_layout(snapshot)
    graph = _picture(
        snapshot,
        {"camera": {**snapshot["sources"][0], "locator": str(tmp_path / "raw.mkv")}},
        {t["trackId"]: t for t in snapshot["layout"]["tracks"]},
        SimpleNamespace(raw_dir=tmp_path),
        Fraction(24),
        96,
    )
    item = graph["operations"][0]["parameters"]["placements"][0]
    assert (
        item["pictureTransform"]
        == snapshot["layout"]["placements"][0]["pictureTransform"]
    )
    assert item["pictureFade"] == {"inFrames": 0, "outFrames": 6}


@pytest.mark.parametrize(
    "defect",
    [
        "unknown-transform",
        "canvas-mismatch",
        "zero-size",
        "fade-overlap",
        "fractional-fade",
        "audio",
    ],
)
def test_unsupported_or_ambiguous_picture_treatments_fail(defect):
    snapshot = deepcopy(treated_snapshot())
    item = snapshot["layout"]["placements"][0]
    if defect == "unknown-transform":
        item["pictureTransform"]["rotation"] = 90
    elif defect == "canvas-mismatch":
        item["pictureTransform"]["canvasWidth"] = 256
    elif defect == "zero-size":
        item["pictureTransform"]["width"] = 0
    elif defect == "fade-overlap":
        item["pictureFade"] = {"inFrames": 20, "outFrames": 20}
    elif defect == "fractional-fade":
        item["pictureFade"]["outFrames"] = 1.5
    else:
        item["mediaKind"] = "audio"
    with pytest.raises(LayoutError):
        validate_layout(snapshot)
