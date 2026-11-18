"""Selected sound timing requires an atomic reader fence and exact track binding."""

from copy import deepcopy

import pytest

from avo.timeline.contracts import content_hash, required_tracks_readers
from avo.timeline.sound_planning import freeze_sound_choices
from avo.timeline.store import StoreError, atomic_write_json
from tests.test_sound_choices import inputs


def selected_snapshot(tmp_path):
    entry, event, choice, context, clock = inputs(tmp_path)
    selected = freeze_sound_choices(
        [event], [choice], entries=[entry], contexts=[context], clock=clock
    )["choices"][0]
    fit = selected["fit"]
    selection = {
        "contractVersion": "1.0.0",
        "choice": selected,
        "cueId": "cue-sound",
        "generationId": "c" * 64,
        "proposalRef": {
            "path": "edit/motion/sound/proposals/" + "a" * 64 + ".json",
            "sha256": "a" * 64,
        },
        "applicationRef": {
            "path": "edit/motion/sound/requests/" + "b" * 64 + ".json",
            "sha256": "b" * 64,
        },
    }
    layer = {
        "layerId": "sound-layer",
        "order": 1,
        "role": "sfx",
        "source": {
            "locator": str(tmp_path / "sounds/whoosh.wav"),
            "sha256": entry["source"]["sha256"],
            "sizeBytes": entry["source"]["sizeBytes"],
        },
        "channels": selected["mix"]["channelMap"],
        "gainDb": selected["mix"]["gainDb"],
        "regions": [
            {
                "regionId": "sound-region",
                "timebase": {"num": 1, "den": 48000},
                "startTicks": fit["event"]["scheduledAudioStartSample"],
                "endTicks": fit["scheduledAudioEndSample"],
                "cueIds": ["cue-sound"],
            }
        ],
        "provenance": {"soundSelection": selection},
    }
    return {"audioTracks": {"layers": [layer]}, "videoTracks": {"layers": []}}


def test_legacy_metadata_read_never_upgrades_index(footage_project_factory):
    workspace = footage_project_factory()
    workspace.initialize()
    store = workspace.store("tracks")
    before = store.path.read_bytes()
    assert required_tracks_readers({"audioTracks": {"layers": []}}) == ()
    assert store.load_index()["schemaVersion"] == "1.0.0"
    assert store.path.read_bytes() == before


def test_generic_publication_fences_sound_in_the_same_index_replacement(
    tmp_path, footage_project_factory
):
    workspace = footage_project_factory()
    workspace.initialize()
    snapshot = selected_snapshot(tmp_path)
    store = workspace.store("tracks")
    store.append_revision(snapshot=snapshot, actor="fixture", reason="Selected sound")
    index = store.load_index()
    assert index["schemaVersion"] == "2.0.0"
    assert index["requiredReaderCapabilities"] == ["sound-selection-v1"]
    assert required_tracks_readers(snapshot) == ("sound-selection-v1",)
    downgraded = {k: v for k, v in index.items() if k != "requiredReaderCapabilities"}
    downgraded["schemaVersion"] = "1.0.0"
    atomic_write_json(store.path, downgraded)
    with pytest.raises((StoreError, ValueError), match="sound|reader|capabilit"):
        store.load_index()


@pytest.mark.parametrize(
    "problem",
    [
        "source",
        "timing",
        "cue",
        "role",
        "channel",
        "fit-clock",
        "marker",
        "reference",
        "duplicate",
    ],
)
def test_selected_sound_cannot_rebind_a_frozen_choice_to_different_track_behavior(
    tmp_path, problem
):
    snapshot = selected_snapshot(tmp_path)
    layer = snapshot["audioTracks"]["layers"][0]
    selection = layer["provenance"]["soundSelection"]
    chosen = selection["choice"]
    if problem == "source":
        layer["source"]["sha256"] = "f" * 64
    elif problem == "timing":
        layer["regions"][0]["startTicks"] += 1
    elif problem == "cue":
        layer["regions"][0]["cueIds"] = ["unselected-cue"]
    elif problem == "role":
        layer["role"] = "music"
    elif problem == "channel":
        layer["channels"] = [1, 1]
    elif problem == "fit-clock":
        chosen["fit"]["event"]["scheduledAudioStartSample"] += 1
        chosen["fit"]["fitHash"] = content_hash(
            {k: v for k, v in chosen["fit"].items() if k != "fitHash"}
        )
    elif problem == "marker":
        chosen["sourceEntry"]["marker"]["reviewerRef"] = "changed"
    elif problem == "reference":
        selection["proposalRef"]["path"] = (
            "edit/motion/sound/requests/" + "a" * 64 + ".json"
        )
    else:
        snapshot["audioTracks"]["layers"].append(
            {**deepcopy(layer), "layerId": "duplicate-contribution"}
        )
    chosen["choiceHash"] = content_hash(
        {k: v for k, v in chosen.items() if k != "choiceHash"}
    )
    with pytest.raises(ValueError):
        required_tracks_readers(snapshot)


def test_legacy_audio_projection_rejects_selected_native_sound_timing(tmp_path):
    from avo.adapters.media.audio_tracks import AudioGraphError, compile_audio_layers

    layers = selected_snapshot(tmp_path)["audioTracks"]["layers"]
    with pytest.raises(AudioGraphError, match="native"):
        compile_audio_layers(layers)


def test_invalid_frozen_marker_fails_as_a_store_error_before_publication(
    tmp_path, footage_project_factory
):
    workspace = footage_project_factory()
    workspace.initialize()
    store = workspace.store("tracks")
    snapshot = selected_snapshot(tmp_path)
    choice = snapshot["audioTracks"]["layers"][0]["provenance"]["soundSelection"][
        "choice"
    ]
    choice["sourceEntry"]["marker"]["reviewerRef"] = "changed-review"
    choice["choiceHash"] = content_hash(
        {k: v for k, v in choice.items() if k != "choiceHash"}
    )
    before = store.path.read_bytes()
    with pytest.raises(StoreError, match="sound choice identity"):
        store.append_revision(
            snapshot=snapshot, actor="fixture", reason="Invalid sound"
        )
    assert store.path.read_bytes() == before
    assert store.load_index()["headRevisionId"] is None
