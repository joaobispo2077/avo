"""Compile frozen sound choices into the existing absolute native proof graph."""

from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from .contracts import content_hash, validate_document
from .event_clock import frame_to_sample
from .sound_planning import SCHEMA, SoundPlanningError, _previous_sound_choices


def _append_exact(collection, key, additions):
    indexed = {item[key]: item for item in collection}
    if len(indexed) != len(collection):
        raise SoundPlanningError("Existing proof identities are duplicated")
    for item in additions:
        identity = item[key]
        if identity in indexed:
            if indexed[identity] != item:
                raise SoundPlanningError(
                    "Selected sound conflicts with an existing proof identity"
                )
        else:
            collection.append(item)
            indexed[identity] = item


def _check_choice_clock(choice, rate, region):
    clock = choice["fit"]["clock"]
    fps = clock["frameRate"]
    end = frame_to_sample(
        clock["programEndFrame"],
        frame_rate_num=fps["num"],
        frame_rate_den=fps["den"],
        sample_rate=48000,
    )
    if (
        clock["sampleRate"] != 48000
        or Fraction(fps["num"], fps["den"]) != Fraction(rate["num"], rate["den"])
        or end != region["endSampleExclusive"]
    ):
        raise SoundPlanningError("Selected sound differs from the actual program clock")


def _program_range(execution, choices):
    graph, output = execution["audioGraph"], execution["output"]
    validate_document(graph, "avo.proof-plan.schema.json#/$defs/audioGraph")
    if graph["sampleRate"] != 48000 or output["audioSampleRate"] != 48000:
        raise SoundPlanningError(
            "Selected native sound mixing requires 48000 Hz output"
        )
    encodes = [op for op in graph["operations"] if op["kind"] == "encode"]
    if len(encodes) != 1 or encodes[0]["range"]["startSample"] != 0:
        raise SoundPlanningError("Selected sound requires one complete program encode")
    region, rate = encodes[0]["range"], output["frameRate"]
    validate_document(rate, "avo.proof-plan.schema.json#/$defs/frameRate")
    for choice in choices:
        _check_choice_clock(choice, rate, region)
    return region


def _source(choice, source):
    validate_document(source, SCHEMA + "#/$defs/compileSource")
    path = source["locator"]
    if not Path(path).is_absolute() or "://" in path or path.startswith(("\\\\", "//")):
        raise SoundPlanningError("Selected sound requires an absolute local source")
    if source["sha256"] != choice["fit"]["source"]["sourceSha256"]:
        raise SoundPlanningError("Selected sound source differs from its frozen choice")
    return deepcopy(source)


def _ducking(choice, node_id, sidechains, known):
    ducking = choice["mix"]["ducking"]
    if ducking is None:
        return None
    nodes = sidechains.get(ducking["sidechainLayerId"], [])
    if not nodes or set(nodes) - known or len(nodes) != len(set(nodes)):
        raise SoundPlanningError("Sound ducking requires exact current dialogue nodes")
    if not (
        1 <= ducking["amountDb"] <= 20
        and 0.01 <= ducking["attackMs"] <= 2000
        and 0.01 <= ducking["releaseMs"] <= 9000
    ):
        raise SoundPlanningError("Selected ducking exceeds native mix support")
    return {
        "nodeId": node_id,
        "sidechainNodeIds": list(nodes),
        **{k: ducking[k] for k in ("amountDb", "attackMs", "releaseMs")},
    }


def _contribution(choice, source, sidechains, known):
    fit, mix, entry = choice["fit"], choice["mix"], choice["sourceEntry"]
    if mix["gainDb"] > 30:
        raise SoundPlanningError("Selected gain exceeds native mix support")
    node_id = "sound-" + content_hash(choice["eventId"])[:24]
    source_id = (
        "sound-source-" + content_hash([entry["entryId"], source["sha256"]])[:24]
    )
    region = {
        "startSample": fit["event"]["scheduledAudioStartSample"],
        "endSampleExclusive": fit["scheduledAudioEndSample"],
    }
    node = {
        "nodeId": node_id,
        "kind": "sfx",
        "sourceSampleRate": entry["measurement"]["sampleRate"],
        "targetSampleRate": 48000,
        "sourceLayout": mix["sourceLayout"],
        "targetLayout": mix["targetLayout"],
        "channelMap": mix["channelMap"],
        "latencyCompensationSamples": 0,
        "sourceRange": fit["trimRange"],
        "outputRange": region,
    }
    parameters = {
        "trim": {"nodeId": node_id, "sourceId": source_id, "source": source},
        "gain": {"nodeId": node_id, "gainDb": mix["gainDb"]},
        "fade": {
            "nodeId": node_id,
            "fadeInSamples": mix["fadeInSamples"],
            "fadeOutSamples": mix["fadeOutSamples"],
        },
    }
    duck = _ducking(choice, node_id, sidechains, known)
    if duck is not None:
        parameters["duck"] = duck
    operations = [
        {
            "operationId": node_id + "-" + kind,
            "kind": kind,
            "range": deepcopy(region),
            "parameters": value,
        }
        for kind, value in parameters.items()
    ]
    event = {
        **{k: v for k, v in fit["event"].items() if k != "scheduledAudioStartSample"},
        "sourceRange": fit["trimRange"],
        "audio": {"nodeId": node_id},
        "entryEffectIds": [],
        "validation": {"required": True},
    }
    validate_document(event, "avo.proof-plan.schema.json#/$defs/timedEvent")
    return node, operations, event, source_id


def _extend_mix(operation, region, original_ids, identities):
    if operation["range"] != region or set(operation["parameters"]) != {"nodeIds"}:
        raise SoundPlanningError(
            "Existing program mix cannot be extended without changing its policy"
        )
    previous = operation["parameters"]["nodeIds"]
    if len(previous) != len(set(previous)) or set(previous) != original_ids:
        raise SoundPlanningError(
            "Existing program mix does not cover its exact original nodes"
        )
    operation["parameters"]["nodeIds"] = previous + [
        identity for identity in identities if identity not in original_ids
    ]


def _program_mix(graph, region, original_ids):
    mixes = [op for op in graph["operations"] if op["kind"] == "mix"]
    if len(mixes) > 1:
        raise SoundPlanningError("Selected sound requires one explicit program mix")
    identities = [node["nodeId"] for node in graph["nodes"]]
    if mixes:
        _extend_mix(mixes[0], region, original_ids, identities)
    else:
        operation = {
            "operationId": "selected-sound-mix",
            "kind": "mix",
            "range": deepcopy(region),
            "parameters": {"nodeIds": identities},
        }
        _append_exact(graph["operations"], "operationId", [operation])


def _append_contribution(result, choice, source, sidechains, known):
    graph = result["audioGraph"]
    node, operations, event, source_id = _contribution(
        choice, source, sidechains, known
    )
    _append_exact(graph["nodes"], "nodeId", [node])
    _append_exact(graph["operations"], "operationId", operations)
    _append_exact(result["events"], "eventId", [event])
    lock = result.setdefault("canonicalInputLock", {})
    key = "source:" + source_id
    if key in lock and lock[key] != source["sha256"]:
        raise SoundPlanningError(
            "Selected sound conflicts with the original source lock"
        )
    lock[key] = source["sha256"]


def _active_choices(choices, source_refs):
    active = [c for c in choices if c["fit"]["status"] == "fit"]
    if set(source_refs) != {c["eventId"] for c in active}:
        raise SoundPlanningError(
            "Exact source references are required for selected sound events"
        )
    return active


def _graph_ids(graph):
    all_ids = {node["nodeId"] for node in graph["nodes"]}
    lead_ids = {node["nodeId"] for node in graph["nodes"] if node["kind"] == "source"}
    return all_ids, lead_ids


def append_selected_sound(execution, choices, *, source_refs, sidechain_nodes=None):
    """Pure deterministic compilation; native execution still admits original bytes.

    Canonical publication/head/catalogue checks belong to the calling owner. This
    route starts no decoder, changes no dialogue/music processing, and grants no
    listening acceptance. Exact replay cannot double a selected contribution.
    """
    try:
        choices = list(_previous_sound_choices(choices).values())
        region = _program_range(execution, choices)
        active = _active_choices(choices, source_refs)
        result = deepcopy(execution)
        graph = result["audioGraph"]
        original_ids, known = _graph_ids(graph)
        for choice in active:
            source = _source(choice, source_refs[choice["eventId"]])
            _append_contribution(result, choice, source, sidechain_nodes or {}, known)
        if active:
            _program_mix(graph, region, original_ids)
        validate_document(graph, "avo.proof-plan.schema.json#/$defs/audioGraph")
        return result
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise SoundPlanningError(str(error)) from error


__all__ = ["append_selected_sound"]
