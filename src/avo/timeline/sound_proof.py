"""Compile only current published sound choices into the ordinary native graph."""

import re
from copy import deepcopy
from fractions import Fraction

from .motion_retention import _Retention
from .sound_compilation import append_selected_sound
from .sound_fitting import SoundPlanningError
from .sound_planning import _sound_opportunity
from .sound_tracks import _sound_layers, validate_sound_bindings

NODE = re.compile(r"^sound-[a-f0-9]{24}$")
SOURCE = re.compile(r"^source:sound-source-[a-f0-9]{24}$")


def _require(condition, message):
    if not condition:
        raise SoundPlanningError(message)


def _owned(value):
    return isinstance(value, str) and NODE.fullmatch(value) is not None


def _snapshot(workspace, name):
    store = workspace.store(name)
    index = store.load_index()
    return (
        {}
        if index["headRevisionId"] is None
        else store.revision(index["headRevisionId"])["snapshot"]
    )


def _base_execution(execution, event_ids):
    result = deepcopy(execution)
    _base_audio(result["audioGraph"])
    result["events"] = [
        event
        for event in result.get("events", [])
        if event["eventId"] not in event_ids
        and not _owned((event.get("audio") or {}).get("nodeId"))
    ]
    result["canonicalInputLock"] = {
        key: value
        for key, value in result.get("canonicalInputLock", {}).items()
        if SOURCE.fullmatch(key) is None
    }
    return result


def _base_audio(graph):
    graph["nodes"] = [node for node in graph["nodes"] if not _owned(node["nodeId"])]
    operations = []
    for operation in graph["operations"]:
        if (
            _owned(operation["parameters"].get("nodeId"))
            or operation["operationId"] == "selected-sound-mix"
        ):
            continue
        if operation["kind"] == "mix":
            parameters = operation["parameters"]
            if "nodeIds" in parameters:
                parameters["nodeIds"] = [
                    value for value in parameters["nodeIds"] if not _owned(value)
                ]
        operations.append(operation)
    graph["operations"] = operations


class _Selections:
    def __init__(self, workspace, tracks):
        self.workspace, self.tracks = workspace, tracks
        self.bmap = _snapshot(workspace, "bmap")
        validate_sound_bindings(self.bmap, tracks)
        self.retained = _Retention(workspace)
        self.contexts = {}
        self.animation = None
        self.cmap = None

    def _camera_animation(self, intent):
        if "cameraAnchor" not in intent:
            return None
        if self.animation is None:
            self.animation = _snapshot(self.workspace, "animation")
        return self.animation

    def _source_cmap(self, intent):
        if "sourceAnchor" not in intent:
            return None
        if self.cmap is None:
            self.cmap = _snapshot(self.workspace, "cmap")
        return self.cmap

    def _published(self, layer):
        selected = layer["provenance"]["soundSelection"]
        _require(
            selected.get("sourceRef") is not None
            and selected.get("context") is not None,
            "Selected sound needs complete source/visual admission",
        )
        reader = self.retained.sound_retention
        receipt = reader.application(selected["applicationRef"])
        _require(
            receipt["state"] == "committed",
            "Selected sound publication is not committed",
        )
        prepared = {
            value["layerId"]: value
            for value in _sound_layers(receipt["prepared"]["tracks"]["snapshot"])
        }
        original = prepared.get(layer["layerId"], {})
        _require(
            (original.get("provenance") or {}).get("soundSelection") == selected,
            "Selected sound differs from its actual published recipe",
        )
        request = reader.reference(receipt["requestRef"], "applyRequest")
        proposal = reader.reference(receipt["proposalRef"], "proposal")
        self._visual(selected, request, proposal)
        return selected

    def _visual(self, selected, request, proposal):
        choice = selected["choice"]
        record = next(
            (
                value
                for value in proposal["opportunities"]
                if value["eventId"] == choice["eventId"]
            ),
            None,
        )
        _require(
            record is not None, "Selected sound has no actual proposed opportunity"
        )
        cue_id = choice["fit"]["opportunity"]["cueId"]
        cue = next(
            (cue for cue in self.bmap.get("cues", []) if cue["cueId"] == cue_id), None
        )
        _require(cue is not None, "Selected sound visual anchor is missing")
        role = self.retained.sound_retention.application_service._visual_role(
            record, cue
        )
        _require(
            role == selected["context"]["role"], "Selected sound visual role changed"
        )
        fps = choice["fit"]["clock"]["frameRate"]
        item = {"itemId": (cue.get("contentRef") or {}).get("itemId", choice["itemId"])}
        part = {
            "cueId": cue_id,
            "timing": {"start": cue["start"], "end": cue["end"]},
            "cue": cue,
        }
        fresh = _sound_opportunity(
            item,
            part,
            record["intent"],
            Fraction(fps["num"], fps["den"]),
            animation=self._camera_animation(record["intent"]),
            cmap=self._source_cmap(record["intent"]),
        )
        _require(
            fresh == choice["fit"]["opportunity"],
            "Selected sound visual timing or identity changed",
        )
        context = next(
            (value for value in request["contexts"] if value["cueId"] == cue_id), None
        )
        _require(
            context is not None, "Selected sound lacks its explicit visual context"
        )
        self.contexts.setdefault(cue_id, []).append(context)

    def load(self):
        self.workspace.require_active("tracks")
        selections = [
            self._published(layer)
            for layer in sorted(
                _sound_layers(self.tracks), key=lambda layer: layer["order"]
            )
            if not layer.get("mute", False)
        ]
        self._order(selections)
        return selections

    def _order(self, selections):
        groups = {}
        for selected in selections:
            groups.setdefault(selected["context"]["cueId"], []).append(
                selected["choice"]["eventId"]
            )
        for cue_id, events in groups.items():
            if len(events) > 1:
                _require(
                    any(
                        [
                            value
                            for value in context["orderedEventIds"]
                            if value in events
                        ]
                        == events
                        for context in self.contexts[cue_id]
                    ),
                    "Selected sound stack differs from its exact ordered disposition",
                )


def _sidechains(tracks, graph, choices):
    layers = {
        layer["layerId"]: layer
        for layer in (tracks.get("audioTracks") or {}).get("layers", [])
    }
    nodes = {
        node["nodeId"]: node for node in graph["nodes"] if node["kind"] == "source"
    }
    references = {}
    for operation in graph["operations"]:
        if (
            operation["kind"] == "trim"
            and operation["parameters"].get("nodeId") in nodes
        ):
            references.setdefault(operation["parameters"]["nodeId"], []).append(
                operation["parameters"]["source"]
            )
    result = {}
    for choice in choices:
        duck = choice["mix"]["ducking"]
        if duck is not None:
            identity = duck["sidechainLayerId"]
            result[identity] = _dialogue_nodes(layers.get(identity), nodes, references)
    return result


def _dialogue_nodes(layer, nodes, references):
    _require(
        layer is not None
        and layer["role"] == "dialogue"
        and not layer.get("mute", False),
        "Sound ducking requires a current unmuted dialogue layer",
    )
    matches = []
    streams = set()
    for identity, sources in references.items():
        if (
            len(sources) == 1
            and sources[0]["sha256"] == layer["source"]["sha256"]
            and _dialogue_channels(layer, nodes[identity])
        ):
            matches.append(identity)
            streams.add(sources[0]["streamIndex"])
    _require(
        matches and len(streams) == 1,
        "Dialogue sidechain source/stream/channel mapping is missing or ambiguous",
    )
    return matches


def _dialogue_channels(layer, node):
    channels = layer.get("channels") or []
    return node["channelMap"] == channels or (
        len(channels) == 1
        and node["targetLayout"] == "stereo"
        and node["channelMap"] == channels * 2
    )


def _same_sound_execution(actual, expected):
    return all(
        actual.get(key) == expected.get(key)
        for key in ("audioGraph", "events", "canonicalInputLock")
    )


def _selected_ranges(choices):
    ranges = {}
    for choice in choices:
        fit = choice["fit"]
        ranges.setdefault(fit["source"]["sourceSha256"], []).append(
            (fit["event"]["scheduledAudioStartSample"], fit["scheduledAudioEndSample"])
        )
    return ranges


def _reject_duplicate_sources(graph, choices):
    nodes = {node["nodeId"]: node for node in graph["nodes"] if node["kind"] == "sfx"}
    ranges = _selected_ranges(choices)
    for operation in graph["operations"]:
        parameters = operation["parameters"]
        node = nodes.get(parameters.get("nodeId"))
        if operation["kind"] != "trim" or node is None:
            continue
        source = parameters.get("source") or {}
        _require(
            source.get("sha256") is not None,
            "Existing SFX needs an explicit source before combining selected sound",
        )
        output = node["outputRange"]
        overlap = any(
            output["startSample"] < end and start < output["endSampleExclusive"]
            for start, end in ranges.get(source["sha256"], [])
        )
        _require(
            not overlap,
            "Existing sound duplicates or overlaps a selected source without canonical event ownership",
        )


def compile_canonical_sound(workspace, execution, *, require_applied=False):
    """Metadata admission and deterministic composition; native execution verifies bytes."""
    if execution.get("checkpoint") == "cut-proof":
        _require(
            not any(
                _owned(node["nodeId"]) for node in execution["audioGraph"]["nodes"]
            ),
            "Cut proof cannot include selected sound contributions",
        )
        return deepcopy(execution)
    tracks = _snapshot(workspace, "tracks")
    layers = _sound_layers(tracks)
    selections = _Selections(workspace, tracks).load() if layers else []
    choices = [selected["choice"] for selected in selections]
    base = _base_execution(execution, {choice["eventId"] for choice in choices})
    if choices:
        _reject_duplicate_sources(base["audioGraph"], choices)
        _require(
            all(
                choice["mix"]["targetLayout"] == execution["output"]["channelLayout"]
                for choice in choices
            ),
            "Selected sound differs from the output channel layout",
        )
        sources = {
            selected["choice"]["eventId"]: selected["sourceRef"]
            for selected in selections
        }
        base = append_selected_sound(
            base,
            choices,
            source_refs=sources,
            sidechain_nodes=_sidechains(tracks, base["audioGraph"], choices),
        )
    if require_applied:
        _require(
            _same_sound_execution(execution, base),
            "Proof changes or omits its current canonical selected sound",
        )
    return base
