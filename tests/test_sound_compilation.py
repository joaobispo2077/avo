"""Sound compilation preserves source processing and rejects ambiguous ownership."""

from copy import deepcopy

import pytest

from avo.timeline.sound_compilation import append_selected_sound
from avo.timeline.sound_planning import SoundPlanningError, freeze_sound_choices
from tests.test_sound_choices import inputs


def prepared(tmp_path, *, duck=False):
    entry, event, choice, context, clock = inputs(tmp_path)
    if duck:
        choice["mix"]["ducking"] = {
            "sidechainLayerId": "dialogue",
            "amountDb": 8,
            "attackMs": 20,
            "releaseMs": 250,
        }
    choices = freeze_sound_choices(
        [event], [choice], entries=[entry], contexts=[context], clock=clock
    )["choices"]
    region = {"startSample": 0, "endSampleExclusive": 180000}
    source = {
        "locator": str(tmp_path / "voice.wav"),
        "sha256": "a" * 64,
        "mediaClass": "source",
        "streamIndex": 0,
    }
    execution = {
        "output": {"frameRate": clock["frameRate"], "audioSampleRate": 48000},
        "canonicalInputLock": {"source:voice": source["sha256"]},
        "events": [],
        "audioGraph": {
            "sampleRate": 48000,
            "singleFinalEncode": True,
            "nodes": [
                {
                    "nodeId": "voice",
                    "kind": "source",
                    "sourceSampleRate": 48000,
                    "targetSampleRate": 48000,
                    "sourceLayout": "stereo",
                    "targetLayout": "stereo",
                    "channelMap": [0, 1],
                    "latencyCompensationSamples": 0,
                    "sourceRange": region,
                    "outputRange": region,
                }
            ],
            "operations": [
                {
                    "operationId": "voice-trim",
                    "kind": "trim",
                    "range": region,
                    "parameters": {
                        "nodeId": "voice",
                        "sourceId": "voice",
                        "source": source,
                    },
                },
                {
                    "operationId": "program-encode",
                    "kind": "encode",
                    "range": region,
                    "parameters": {},
                },
            ],
        },
    }
    refs = {
        event["eventId"]: {
            **source,
            "locator": str(tmp_path / "sounds" / "whoosh.wav"),
            "sha256": entry["source"]["sha256"],
        }
    }
    return execution, choices, refs


@pytest.mark.parametrize(
    "problem",
    [
        "clock",
        "source",
        "remote",
        "duplicate-node",
        "mix-scope",
        "mix-policy",
        "event-conflict",
    ],
)
def test_conflicting_sound_inputs_fail_without_changing_original_execution(
    tmp_path, problem
):
    execution, choices, refs = prepared(tmp_path)
    if problem == "clock":
        execution["output"]["frameRate"]["num"] = 25
    elif problem == "source":
        next(iter(refs.values()))["sha256"] = "f" * 64
    elif problem == "remote":
        next(iter(refs.values()))["locator"] = "https://example.com/unselected.wav"
    elif problem == "duplicate-node":
        execution["audioGraph"]["nodes"].append(
            deepcopy(execution["audioGraph"]["nodes"][0])
        )
    elif problem.startswith("mix"):
        execution["audioGraph"]["operations"].append(
            {
                "operationId": "existing-mix",
                "kind": "mix",
                "range": {"startSample": 0, "endSampleExclusive": 180000},
                "parameters": {
                    "nodeIds": ["unselected"] if problem == "mix-scope" else ["voice"],
                    **({"normalize": True} if problem == "mix-policy" else {}),
                },
            }
        )
    else:
        execution["events"].append({"eventId": choices[0]["eventId"], "role": "music"})
    before = deepcopy(execution)
    with pytest.raises(SoundPlanningError):
        append_selected_sound(execution, choices, source_refs=refs)
    assert execution == before


def test_existing_mix_and_voice_processing_keep_their_original_identity(tmp_path):
    execution, choices, refs = prepared(tmp_path)
    mix = {
        "operationId": "existing-mix",
        "kind": "mix",
        "range": {"startSample": 0, "endSampleExclusive": 180000},
        "parameters": {"nodeIds": ["voice"]},
    }
    execution["audioGraph"]["operations"].append(mix)
    result = append_selected_sound(execution, choices, source_refs=refs)
    assert result["audioGraph"]["nodes"][0] == execution["audioGraph"]["nodes"][0]
    assert (
        result["audioGraph"]["operations"][:2]
        == execution["audioGraph"]["operations"][:2]
    )
    current = [op for op in result["audioGraph"]["operations"] if op["kind"] == "mix"]
    assert len(current) == 1 and current[0]["operationId"] == "existing-mix"
    assert current[0]["parameters"]["nodeIds"][0] == "voice"
    assert append_selected_sound(result, choices, source_refs=refs) == result


def test_ducking_requires_exact_supplied_current_dialogue_nodes(tmp_path):
    execution, choices, refs = prepared(tmp_path, duck=True)
    with pytest.raises(SoundPlanningError, match="dialogue nodes"):
        append_selected_sound(execution, choices, source_refs=refs)
    result = append_selected_sound(
        execution, choices, source_refs=refs, sidechain_nodes={"dialogue": ["voice"]}
    )
    duck = next(op for op in result["audioGraph"]["operations"] if op["kind"] == "duck")
    assert duck["parameters"]["sidechainNodeIds"] == ["voice"]
    assert duck["parameters"]["amountDb"] == 8
