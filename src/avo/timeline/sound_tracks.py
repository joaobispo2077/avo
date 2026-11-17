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


def validate_sound_tracks(snapshot):
    layers = _sound_layers(snapshot)
    if not layers:
        return ()
    from .sound_choices import _previous_sound_choices

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
    ids = [layer.get("layerId") for layer in snapshot["audioTracks"]["layers"]]
    _require(len(ids) == len(set(ids)), "layer identities are duplicated")
    return CAPABILITIES


__all__ = ["validate_sound_tracks"]
