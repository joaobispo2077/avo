"""Explicit frame repetition preserves source time and remains opt-in."""

from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace

import pytest

from avo.timeline.import_layout import LayoutError, validate_layout
from avo.timeline.initial_cut_placed import _picture
from avo.timeline.mapping import cmap_output_to_raw, cmap_raw_to_output
from tests.test_timeline_import_layout import placed_snapshot


def sampling_snapshot():
    snapshot = placed_snapshot()
    snapshot["importOutput"]["frameRate"]["num"] = 48
    layout = snapshot["layout"]
    layout["programClock"]["frameRate"]["num"] = 48
    layout["programClock"]["timebase"]["den"] = 48
    times = [layout["duration"]]
    for item in [*layout["placements"], *layout["gaps"]]:
        times.extend([item["start"], item["end"]])
        if item.get("mediaKind") == "video":
            item["pictureSampling"] = "repeat-2x"
    for value in times:
        value["ticks"] *= 2
        value["timebase"]["den"] = 48
    return snapshot


def test_explicit_repetition_compiles_without_changing_source_intervals(tmp_path):
    snapshot = sampling_snapshot()
    validate_layout(snapshot)
    graph = _picture(
        snapshot,
        {"camera": {**snapshot["sources"][0], "locator": str(tmp_path / "raw.mkv")}},
        {t["trackId"]: t for t in snapshot["layout"]["tracks"]},
        SimpleNamespace(raw_dir=tmp_path),
        Fraction(48),
        192,
    )
    picture = graph["operations"][0]["parameters"]["placements"][0]
    assert picture["pictureSampling"] == "repeat-2x"
    assert picture["sourceRange"] == {
        "startTicks": 0,
        "endTicks": 24,
        "timebase": {"num": 1, "den": 24},
    }
    assert picture["outputRange"] == {"startFrame": 48, "endFrameExclusive": 96}


def test_each_repeated_output_frame_maps_to_the_same_native_source_frame():
    snapshot = sampling_snapshot()
    for output, raw in [(48, 0), (49, 0), (50, 1), (51, 1), (95, 23)]:
        assert cmap_output_to_raw(snapshot, output, placement_id="first") == (
            "camera",
            raw,
        )
    assert cmap_output_to_raw(snapshot, 96, placement_id="first") is None
    assert cmap_raw_to_output(snapshot, "camera", 1, placement_id="first") == 50


@pytest.mark.parametrize("defect", ["unknown-mode", "fractional-source-frame", "still"])
def test_invalid_sampling_never_acquires_canonical_authority(defect):
    snapshot = deepcopy(sampling_snapshot())
    item = snapshot["layout"]["placements"][0]
    if defect == "unknown-mode":
        item["pictureSampling"] = "optical-flow"
    elif defect == "fractional-source-frame":
        item["in"]["timebase"]["den"] = 48
        item["in"]["ticks"] = 1
        item["out"]["timebase"]["den"] = 48
        item["out"]["ticks"] = 97
    else:
        item["mediaKind"] = "still"
    with pytest.raises(LayoutError):
        validate_layout(snapshot)
