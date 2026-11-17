"""Strict metadata bindings for selected sound tracks; no source or model execution."""

from .contracts import ContractError, validate_document

CAPABILITIES = ("sound-selection-v1",)
SCHEMA = "avo.sound-selection.schema.json"


def _require(condition, message):
    if not condition:
        raise ContractError("Selected sound track: " + message)


def _reference(reference, collection):
    expected = "edit/motion/sound/" + collection + "/" + reference["sha256"] + ".json"
    _require(
        reference["path"] == expected,
        "reference does not name its exact typed sound document",
    )


def _bound_layer(layer, selection):
    choice = selection["choice"]
    fit, mix = choice["fit"], choice["mix"]
    _require(
        fit["status"] == "fit", "silence/unresolved choices cannot supply a sound layer"
    )
    entry = choice["sourceEntry"]
    _require(layer["role"] == "sfx", "selected sound requires the sfx track role")
    _require(
        all(
            layer["source"][key] == entry["source"][key]
            for key in ("sha256", "sizeBytes")
        ),
        "source differs from the frozen sound entry",
    )
    _require(
        layer.get("channels") == mix["channelMap"]
        and layer.get("gainDb", 0) == mix["gainDb"],
        "channels/gain differ from the frozen sound choice",
    )
    _require(
        not layer.get("fades") and not layer.get("ducking"),
        "fades/ducking must use the one frozen sound mix",
    )
    _require(len(layer["regions"]) == 1, "one selected event requires one exact region")
    region = layer["regions"][0]
    _require(
        region.get("timebase") == {"num": 1, "den": fit["clock"]["sampleRate"]},
        "sound region must retain the exact output sample clock",
    )
    _require(
        region["startTicks"] == fit["event"]["scheduledAudioStartSample"]
        and region["endTicks"] == fit["scheduledAudioEndSample"],
        "region differs from the fitted native schedule",
    )
    _require(
        region["cueIds"] == [selection["cueId"]] and region.get("gainDb", 0) == 0,
        "region changes the selected cue or applies a second gain",
    )
    _require(
        not any(region.get(key) for key in ("fadeInTicks", "fadeOutTicks", "ducking")),
        "region would apply a second sound effect policy",
    )
    _admission(layer, selection)


def _admission(layer, selection):
    source, context = selection.get("sourceRef"), selection.get("context")
    _require(
        (source is None) == (context is None), "incomplete source/context admission"
    )
    if source is None:
        return  # Historical metadata prototypes remain inspectable, not renderable.
    _require(
        all(source[key] == layer["source"][key] for key in ("locator", "sha256")),
        "admitted source differs from its selected layer",
    )
    _require(
        context["cueId"] == selection["choice"]["fit"]["opportunity"]["cueId"],
        "admitted context names a different visual cue",
    )


def validate_sound_bindings(bmap, tracks):
    """Validate exact owned audio cues before replacing/removing selected tracks."""
    validate_sound_tracks(tracks)
    cues = {cue["cueId"]: cue for cue in bmap.get("cues", [])}
    _require(len(cues) == len(bmap.get("cues", [])), "cue identities are duplicated")
    for layer in _sound_layers(tracks):
        selection = layer["provenance"]["soundSelection"]
        choice = selection["choice"]
        cue = cues.get(selection["cueId"], {})
        _require(
            cue.get("kind") == "sfx"
            and cue.get("targetLayerId") == layer["layerId"]
            and cue.get("assetRef") == layer["source"]
            and cue.get("audio")
            == {"playbackOwner": "tracks-native", "eventId": choice["eventId"]},
            "selected track does not own its exact BMap audio cue",
        )
        _bound_cue(cue, layer, selection)


def _bound_cue(cue, layer, selection):
    choice = selection["choice"]
    content = cue.get("contentRef") or {}
    _require(
        content.get("soundEventId") == choice["eventId"]
        and content.get("choiceHash") == choice["choiceHash"]
        and content.get("applicationRef") == selection["applicationRef"],
        "selected cue changes choice or application identity",
    )
    region = layer["regions"][0]
    for key, tick_key in (("start", "startTicks"), ("end", "endTicks")):
        _require(
            cue.get(key)
            == {
                "ticks": region[tick_key],
                "timebase": region["timebase"],
                "domain": "cmap-output",
            },
            "selected cue changes the exact fitted schedule",
        )


def _sound_layers(snapshot):
    audio = snapshot.get("audioTracks")
    if not isinstance(audio, dict) or not isinstance(audio.get("layers"), list):
        return []
    return [
        layer
        for layer in audio["layers"]
        if isinstance(layer, dict)
        and isinstance(layer.get("provenance"), dict)
        and "soundSelection" in layer["provenance"]
    ]


def _admitted_contexts(layers):
    groups = {}
    for layer in sorted(layers, key=lambda value: value["order"]):
        selected = layer["provenance"]["soundSelection"]
        context = selected.get("context")
        if context is not None:
            groups.setdefault(context["cueId"], []).append(selected)
    contexts = {}
    for cue_id, selected in groups.items():
        first = selected[0]["context"]
        _require(
            all(s["context"] == first for s in selected),
            "selected group changes its explicit visual disposition",
        )
        contexts[cue_id] = {
            "cueId": cue_id,
            "role": first["role"],
            "syntheticEffectApproved": first["syntheticEffectApproved"],
            "orderedEventIds": [s["choice"]["eventId"] for s in selected]
            if first["orderedLayeringApproved"]
            else [],
        }
    return contexts


def validate_sound_tracks(snapshot):
    layers = _sound_layers(snapshot)
    if not layers:
        return ()
    from .sound_choices import _check_sound_roles, _previous_sound_choices

    choices = []
    for layer in layers:
        validate_document(
            layer,
            "avo.tracks.schema.json#/$defs/tracksSnapshot/properties/audioTracks/properties/layers/items",
        )
        selection = layer["provenance"]["soundSelection"]
        validate_document(selection, SCHEMA + "#/$defs/selectedTrack")
        _reference(selection["proposalRef"], "proposals")
        _reference(selection["applicationRef"], "requests")
        choices.append(selection["choice"])
        _bound_layer(layer, selection)
    _previous_sound_choices(choices)
    contexts = _admitted_contexts(layers)
    _check_sound_roles(
        [c for c in choices if c["fit"]["opportunity"]["cueId"] in contexts], contexts
    )
    ids = [layer.get("layerId") for layer in snapshot["audioTracks"]["layers"]]
    _require(len(ids) == len(set(ids)), "layer identities are duplicated")
    return CAPABILITIES


__all__ = ["validate_sound_bindings", "validate_sound_tracks"]
