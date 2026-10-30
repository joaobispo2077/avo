"""SFX source pre-roll schedules the actual impact on the shared frame clock."""

from copy import deepcopy

import pytest

from avo.adapters.media.proof_audio_bridge import validate_audio_events


def _execution():
    source = {"startSample": 100, "endSampleExclusive": 980}
    node = {
        "nodeId": "pop-one",
        "kind": "sfx",
        "sourceRange": source,
        "sourceSampleRate": 48000,
        "outputRange": {"startSample": 720, "endSampleExclusive": 1600},
    }
    event = {
        "eventId": "pop-impact",
        "role": "sfx",
        "programFrame": 1,
        "visibleRange": None,
        "sourceRange": source,
        "audio": {"nodeId": "pop-one"},
        "transientOffset": {
            "sourceSamples": 80,
            "sourceRate": 48000,
            "resolvedOutputSamples": 80,
        },
        "resolvedImpactSample": 800,
        "entryEffectIds": [],
    }
    return {
        "output": {"frameRate": {"num": 60, "den": 1}},
        "audioGraph": {"sampleRate": 48000, "nodes": [node]},
        "events": [event],
    }


def test_sfx_impact_can_follow_its_declared_source_preroll():
    assert validate_audio_events(_execution()) == {"pop-impact"}


@pytest.mark.parametrize("change", ["offset", "rate", "unknown", "not-sfx"])
def test_false_transient_declarations_fail(change):
    value = deepcopy(_execution())
    event = value["events"][0]
    if change == "offset":
        event["transientOffset"]["resolvedOutputSamples"] = 81
    elif change == "rate":
        event["transientOffset"]["sourceRate"] = 44100
    elif change == "unknown":
        event["transientOffset"]["wallClock"] = 0
    else:
        event["role"] = "music"
    with pytest.raises(RuntimeError, match="transient|clock|role"):
        validate_audio_events(value)
