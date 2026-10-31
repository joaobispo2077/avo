"""Frame-domain Tracks retain exact cue timing through the compatibility boundary."""

import pytest

from avo.timeline.contracts import validate_document
from avo.timeline.tracks import TrackError, compile_video_layers, resolve_tracks


def _snapshot():
    return {
        "videoTracks": {
            "layers": [
                {
                    "layerId": "graphic-one",
                    "order": 0,
                    "role": "graphic",
                    "source": {"locator": "", "sha256": "a" * 64, "sizeBytes": 0},
                    "faceAvoidance": True,
                    "regions": [
                        {
                            "regionId": "region-one",
                            "startTicks": 60,
                            "endTicks": 120,
                            "timebase": {"num": 1, "den": 60},
                            "cueIds": ["cue-one"],
                        }
                    ],
                }
            ]
        }
    }


def _cue():
    return {
        "start": {"ticks": 1000, "timebase": {"num": 1, "den": 1000}},
        "end": {"ticks": 2000, "timebase": {"num": 1, "den": 1000}},
    }


def test_frame_region_schema_and_projection_keep_seconds():
    value = _snapshot()
    region = value["videoTracks"]["layers"][0]["regions"][0]
    validate_document(
        region,
        "avo.tracks.schema.json#/$defs/tracksSnapshot/properties/videoTracks/properties/layers/items/properties/regions/items",
    )
    resolved = resolve_tracks(value, {"cue-one"}, cues={"cue-one": _cue()})
    overlay = compile_video_layers(resolved["videoTracks"]["layers"])["overlays"][0]
    assert overlay["start_in_output"] == 1
    assert overlay["duration"] == 1


def test_numeric_ticks_cannot_hide_shorter_region_in_different_timebase():
    value = _snapshot()
    value["videoTracks"]["layers"][0]["regions"][0]["endTicks"] = 119
    with pytest.raises(TrackError, match="truncates"):
        resolve_tracks(value, {"cue-one"}, cues={"cue-one": _cue()})
