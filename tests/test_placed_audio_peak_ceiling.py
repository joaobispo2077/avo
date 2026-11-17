"""Explicit clip peak protection stays canonical and opt-in."""

from types import SimpleNamespace

import pytest

from avo.timeline.import_layout import LayoutError, validate_layout
from avo.timeline.initial_cut_placed import _audio_source
from tests.test_import_audio_tail import tail_snapshot


def test_placed_peak_ceiling_is_projected_only_when_declared(tmp_path):
    snapshot = tail_snapshot()
    item = snapshot["layout"]["placements"][0]
    item.update(gainDb=10, audioPeakCeilingDbfs=-4.5)
    validate_layout(snapshot)
    source = {**snapshot["sources"][0], "locator": str(tmp_path / "raw.wav")}
    _, operations = _audio_source(
        item, source, SimpleNamespace(raw_dir=tmp_path), 1, None
    )
    gain = next(x for x in operations if x["kind"] == "gain")
    assert gain["parameters"] == {
        "nodeId": "audio-source-0001",
        "gainDb": 10,
        "peakCeilingDbfs": -4.5,
    }
    del item["gainDb"]
    _, ceiling_only = _audio_source(
        item, source, SimpleNamespace(raw_dir=tmp_path), 1, None
    )
    assert (
        next(x for x in ceiling_only if x["kind"] == "gain")["parameters"]["gainDb"]
        == 0
    )
    item["gainDb"] = 10
    del item["audioPeakCeilingDbfs"]
    _, legacy = _audio_source(item, source, SimpleNamespace(raw_dir=tmp_path), 1, None)
    assert next(x for x in legacy if x["kind"] == "gain")["parameters"] == {
        "nodeId": "audio-source-0001",
        "gainDb": 10,
    }


@pytest.mark.parametrize("ceiling", [True, None, -13, 0, "-4.5"])
def test_peak_ceiling_rejects_unbounded_or_ambiguous_values(ceiling):
    snapshot = tail_snapshot()
    snapshot["layout"]["placements"][0]["audioPeakCeilingDbfs"] = ceiling
    with pytest.raises(LayoutError):
        validate_layout(snapshot)


def test_picture_placement_cannot_request_audio_peak_processing():
    from tests.test_timeline_import_layout import placed_snapshot

    snapshot = placed_snapshot()
    snapshot["layout"]["placements"][0]["audioPeakCeilingDbfs"] = -4.5
    with pytest.raises(LayoutError):
        validate_layout(snapshot)
