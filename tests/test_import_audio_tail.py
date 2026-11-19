"""Declared tail silence has no raw-source contributor or implicit time shift."""

from copy import deepcopy

import pytest

from avo.timeline.import_layout import LayoutError, audio_sample_ranges, validate_layout
from avo.timeline.mapping import cmap_output_to_raw
from tests.test_timeline_import_layout import placed_snapshot, program_time, raw_time


def tail_snapshot(tail=5504):
    snapshot = placed_snapshot()
    item = {
        "placementId": "dialogue",
        "elementId": "/audio/dialogue",
        "trackId": "audio",
        "sourceId": "camera",
        "mediaKind": "audio",
        "in": raw_time(0, den=48000),
        "out": raw_time(48000 - tail, den=48000),
        "start": program_time(24),
        "end": program_time(48),
        "enabled": True,
        "audioTailSilenceSamples": tail,
        "routing": {
            "audioSelection": {
                "streamIndex": 0,
                "channels": [0, 1],
                "sourceLayout": "stereo",
                "outputLayout": "stereo",
                "sourceSampleRate": 48000,
            }
        },
        "evidenceOrigin": "editor-declaration",
    }
    snapshot["layout"]["placements"] = [item]
    snapshot["layout"]["gaps"] = []
    snapshot["layout"]["tracks"] = [
        {
            "trackId": "audio",
            "kind": "audio",
            "order": 0,
            "enabled": True,
            "muted": False,
            "evidenceOrigin": "export",
        }
    ]
    return snapshot


def test_tail_preserves_slot_and_shortens_only_source_node():
    snapshot = tail_snapshot()
    validate_layout(snapshot)
    item = snapshot["layout"]["placements"][0]
    source, output = audio_sample_ranges(item)
    assert source == {"startSample": 0, "endSampleExclusive": 42496}
    assert output == {"startSample": 48000, "endSampleExclusive": 90496}
    assert cmap_output_to_raw(snapshot, 45, placement_id="dialogue") == (
        "camera",
        42000,
    )
    assert cmap_output_to_raw(snapshot, 46, placement_id="dialogue") is None


@pytest.mark.parametrize("defect", ["undeclared", "wrong-count", "negative", "picture"])
def test_invalid_tail_is_never_accepted(defect):
    snapshot = deepcopy(tail_snapshot())
    item = snapshot["layout"]["placements"][0]
    if defect == "undeclared":
        item.pop("audioTailSilenceSamples")
    elif defect == "wrong-count":
        item["audioTailSilenceSamples"] += 1
    elif defect == "negative":
        item["audioTailSilenceSamples"] = -1
    else:
        item["mediaKind"] = "video"
    with pytest.raises(LayoutError):
        validate_layout(snapshot)
