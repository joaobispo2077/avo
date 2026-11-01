"""A shared generated overlay must bind every smaller visible event explicitly."""

from copy import deepcopy

import pytest

from avo.adapters.media.proof_executor import _validate_events
from avo.adapters.media.proof_rendered_events import bound_visual_event


def test_shared_asset_record_only_matches_operation_containing_bound_source_frames():
    binding = {
        "eventId": "source-section",
        "role": "authored-graphic",
        "assetFrameRange": {"startFrame": 2, "endFrameExclusive": 5},
    }
    generated = {}
    for index in range(3):
        region = {"startFrame": index * 10, "endFrameExclusive": (index + 1) * 10}
        generated[str(index)] = {
            "operation": {
                "kind": "generated-clip",
                "outputRange": region,
                "parameters": {"sourceRange": region},
            },
            "record": {"parameters": {"eventBindings": [binding]}},
        }
    event = {
        "eventId": "source-section",
        "role": "authored-graphic",
        "visibleRange": {"startFrame": 2, "endFrameExclusive": 5},
    }
    assert bound_visual_event(event, generated)
    generated["duplicate"] = deepcopy(generated["0"])
    assert not bound_visual_event(event, generated)


def _fixture():
    region = {"startFrame": 20, "endFrameExclusive": 40}
    operation = {
        "operationId": "graphic",
        "kind": "overlay-video",
        "outputRange": {"startFrame": 0, "endFrameExclusive": 60},
        "parameters": {"sourceRange": {"startFrame": 0, "endFrameExclusive": 60}},
    }
    event = {
        "eventId": "title-one",
        "role": "authored-graphic",
        "programFrame": 20,
        "visibleRange": region,
        "audio": None,
    }
    generated = {
        "graphic": {
            "operation": operation,
            "record": {
                "parameters": {
                    "eventBindings": [
                        {
                            "eventId": "title-one",
                            "role": "authored-graphic",
                            "assetFrameRange": region,
                        }
                    ]
                }
            },
        }
    }
    execution = {
        "output": {"frameRate": {"num": 60, "den": 1}},
        "audioGraph": {"nodes": [], "sampleRate": 48000},
        "videoGraph": {"operations": [operation]},
        "events": [event],
    }
    return execution, generated


def test_explicit_asset_binding_allows_true_sub_event_visibility():
    execution, generated = _fixture()
    _validate_events(execution, generated)


@pytest.mark.parametrize("fault", ["missing", "shifted", "wrong-role", "ambiguous"])
def test_unbound_or_misprojected_sub_event_is_rejected(fault):
    execution, generated = _fixture()
    bindings = generated["graphic"]["record"]["parameters"]["eventBindings"]
    if fault == "missing":
        bindings.clear()
    elif fault == "shifted":
        generated["graphic"]["operation"]["parameters"]["sourceRange"]["startFrame"] = 1
    elif fault == "wrong-role":
        bindings[0]["role"] = "caption"
    else:
        bindings.append(deepcopy(bindings[0]))
    with pytest.raises(RuntimeError, match="event|binding"):
        _validate_events(execution, generated)
