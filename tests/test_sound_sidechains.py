"""Bind optional sound ducking to the actually rendered dialogue channels."""

from copy import deepcopy

import pytest

from avo.timeline.sound_fitting import SoundPlanningError
from avo.timeline.sound_proof import _sidechains


def routing():
    tracks = {
        "audioTracks": {
            "layers": [
                {
                    "layerId": "microphone",
                    "role": "dialogue",
                    "source": {"sha256": "a" * 64},
                    "channels": [0],
                }
            ]
        }
    }
    graph = {
        "nodes": [
            {
                "nodeId": "recorded-mic",
                "kind": "source",
                "channelMap": [0, 0],
                "targetLayout": "stereo",
            }
        ],
        "operations": [
            {
                "kind": "trim",
                "parameters": {
                    "nodeId": "recorded-mic",
                    "source": {"sha256": "a" * 64, "streamIndex": 2},
                },
            }
        ],
    }
    choices = [{"mix": {"ducking": {"sidechainLayerId": "microphone"}}}]
    return tracks, graph, choices


def test_single_selected_microphone_can_follow_its_rendered_dual_mono_routing():
    tracks, graph, choices = routing()
    before = deepcopy((tracks, graph, choices))
    assert _sidechains(tracks, graph, choices) == {"microphone": ["recorded-mic"]}
    assert (tracks, graph, choices) == before


@pytest.mark.parametrize("problem", ["missing", "muted", "role", "channel", "stream"])
def test_ducking_abstains_for_missing_or_ambiguous_dialogue_routing(problem):
    tracks, graph, choices = routing()
    layer = tracks["audioTracks"]["layers"][0]
    if problem == "missing":
        tracks["audioTracks"]["layers"] = []
    elif problem == "muted":
        layer["mute"] = True
    elif problem == "role":
        layer["role"] = "music"
    elif problem == "channel":
        graph["nodes"][0]["channelMap"] = [1, 1]
    else:
        graph["nodes"].append({**graph["nodes"][0], "nodeId": "other-mic-stream"})
        trim = deepcopy(graph["operations"][0])
        trim["parameters"].update(nodeId="other-mic-stream")
        trim["parameters"]["source"]["streamIndex"] = 1
        graph["operations"].append(trim)
    with pytest.raises(SoundPlanningError):
        _sidechains(tracks, graph, choices)
