"""Data-only scoped publication rules preserve siblings and require exact ownership."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.timeline.sound_application import _Application
from avo.timeline.sound_choices import freeze_sound_choices
from avo.timeline.sound_fitting import SoundPlanningError
from avo.timeline.sound_tracks import validate_sound_bindings, validate_sound_tracks
from tests.test_sound_choices import inputs


def setup(tmp_path, *, ordered=True):
    entry, event, choice, context, clock = inputs(tmp_path)
    events = [event, {**event, "eventId": "second", "role": "tail"}]
    choices = [choice, {**deepcopy(choice), "eventId": "second"}]
    if ordered:
        context["orderedEventIds"] = [c["eventId"] for c in choices]
    else:
        events, choices = events[:1], choices[:1]
    frozen = freeze_sound_choices(
        events, choices, entries=[entry], contexts=[context], clock=clock
    )
    internal = _Application(
        SimpleNamespace(
            workspace=SimpleNamespace(video_id="v1"), authoring=None, catalogue=None
        )
    )
    ref = lambda group: {
        "path": f"edit/motion/sound/{group}/{'a' * 64}.json",
        "sha256": "a" * 64,
    }
    sources = {
        c["eventId"]: {
            "locator": str(tmp_path / "sound.wav"),
            "sha256": entry["source"]["sha256"],
            "mediaClass": "source",
            "streamIndex": 3,
        }
        for c in frozen["choices"]
    }
    snapshot = {
        "bmap": {"cues": []},
        "tracks": {
            "audioTracks": {
                "layers": [
                    {
                        "layerId": "music",
                        "order": 4,
                        "role": "music",
                        "fixture": "untouched",
                    }
                ]
            },
            "videoTracks": {"layers": [{"layerId": "picture", "fixture": "untouched"}]},
        },
    }
    for order, frozen_choice in enumerate(frozen["choices"], 5):
        layer, cue = internal._layer(
            frozen_choice,
            sources[frozen_choice["eventId"]],
            context,
            ref("proposals"),
            ref("requests"),
            "f" * 64,
            order,
        )
        internal._append_layer(snapshot, layer, cue)
    request = {
        "expectedGeneration": "f" * 64,
        "choices": choices,
        "contexts": [context],
    }
    proposal = {
        "opportunities": [{"eventId": e["eventId"], "opportunity": e} for e in events],
        "clock": clock,
    }
    shown = {"proposalRef": ref("proposals")}
    return internal, entry, request, proposal, shown, ref("requests"), sources, snapshot


def test_per_id_update_preserves_unselected_sound_music_and_picture(tmp_path):
    internal, entry, request, proposal, shown, ref, sources, snapshot = setup(tmp_path)
    before = deepcopy(snapshot)
    request["choices"] = request["choices"][1:]
    request["choices"][0]["mix"]["gainDb"] = -18
    prepared = internal._choices(request, proposal, {"entries": [entry]}, snapshot)
    _, advisories = internal._authoring(
        request,
        shown,
        prepared,
        sources,
        snapshot,
        ref,
        {c["cueId"]: c for c in request["contexts"]},
    )
    assert snapshot["tracks"]["videoTracks"] == before["tracks"]["videoTracks"]
    after = {
        layer["layerId"]: layer for layer in snapshot["tracks"]["audioTracks"]["layers"]
    }
    assert after["music"] == before["tracks"]["audioTracks"]["layers"][0]
    assert (
        after[before["tracks"]["audioTracks"]["layers"][1]["layerId"]]
        == before["tracks"]["audioTracks"]["layers"][1]
    )
    assert len(after) == 3
    (overlap,) = [row for row in advisories if row["code"] == "overlapping-sounds"]
    assert set(overlap["eventIds"]) == {"reveal-one", "second"}
    assert overlap["assessment"] == "timing-only"


def test_publication_repetition_window_includes_unchanged_siblings(tmp_path):
    internal, entry, request, proposal, shown, ref, sources, snapshot = setup(tmp_path)
    updated = proposal["opportunities"][1]["opportunity"]
    updated["programFrame"] = 45
    request["choices"] = request["choices"][1:]
    prepared = internal._choices(request, proposal, {"entries": [entry]}, snapshot)
    contexts = {c["cueId"]: c for c in request["contexts"]}
    for window, expect_repeat in [(624, False), (625, True)]:
        _, advisories = internal._authoring(
            request,
            shown,
            prepared,
            sources,
            deepcopy(snapshot),
            ref,
            contexts,
            repetition_window_ms=window,
        )
        repeats = [row for row in advisories if row["code"] == "repeated-source"]
        assert bool(repeats) is expect_repeat
        if expect_repeat:
            assert repeats[0]["eventIds"] == ["reveal-one", "second"]


def test_new_second_sound_cannot_borrow_approval_from_preserved_single_sound(tmp_path):
    internal, entry, request, proposal, shown, ref, sources, snapshot = setup(
        tmp_path, ordered=False
    )
    first = request["choices"][0]["eventId"]
    second = {**deepcopy(request["choices"][0]), "eventId": "second"}
    request["choices"] = [second]
    request["contexts"][0]["orderedEventIds"] = [first, "second"]
    proposal["opportunities"].append(
        {
            "eventId": "second",
            "opportunity": {
                **proposal["opportunities"][0]["opportunity"],
                "eventId": "second",
            },
        }
    )
    prepared = internal._choices(request, proposal, {"entries": [entry]}, snapshot)
    sources["second"] = sources[first]
    with pytest.raises(SoundPlanningError, match="explicit reselection"):
        internal._authoring(
            request,
            shown,
            prepared,
            sources,
            snapshot,
            ref,
            {c["cueId"]: c for c in request["contexts"]},
        )


@pytest.mark.parametrize(
    "problem", ["cue-id", "choice", "schedule", "source", "stream-source", "context"]
)
def test_selected_binding_cannot_delete_or_play_an_unowned_cue(tmp_path, problem):
    _, _, _, _, _, _, _, snapshot = setup(tmp_path)
    layer = snapshot["tracks"]["audioTracks"]["layers"][1]
    selected = layer["provenance"]["soundSelection"]
    cue = snapshot["bmap"]["cues"][0]
    if problem == "cue-id":
        selected["cueId"] = "unrelated"
    elif problem == "choice":
        cue["contentRef"]["choiceHash"] = "b" * 64
    elif problem == "schedule":
        cue["start"]["ticks"] += 1
    elif problem == "source":
        cue["assetRef"]["sha256"] = "b" * 64
    elif problem == "stream-source":
        selected["sourceRef"]["sha256"] = "b" * 64
    else:
        selected["context"]["cueId"] = "different-visual"
    with pytest.raises(ValueError):
        validate_sound_bindings(snapshot["bmap"], snapshot["tracks"])


def test_selected_track_reader_rechecks_explicit_ordered_stack_disposition(tmp_path):
    _, _, _, _, _, _, _, snapshot = setup(tmp_path)
    for layer in snapshot["tracks"]["audioTracks"]["layers"][1:]:
        layer["provenance"]["soundSelection"]["context"]["orderedLayeringApproved"] = (
            False
        )
    with pytest.raises(ValueError, match="one entry SFX"):
        validate_sound_tracks(snapshot["tracks"])


def test_retiring_one_event_preserves_ordered_siblings_and_their_original_context(
    tmp_path,
):
    internal, entry, request, proposal, shown, ref, _, snapshot = setup(tmp_path)
    before = deepcopy(snapshot)
    request["choices"] = request["choices"][:1]
    request["choices"][0].update(entryId=None, trimRange=None, mix=None)
    request["contexts"] = []
    proposal["opportunities"] = []
    proposal["clock"] = {**proposal["clock"], "programEndFrame": 1}
    prepared = internal._choices(request, proposal, {"entries": [entry]}, snapshot)
    removed = prepared["choices"][0]
    assert removed["fit"]["status"] == "silence"
    assert removed["fit"]["clock"]["programEndFrame"] > 1
    assert prepared["changes"][0]["before"]["entryId"] == entry["entryId"]
    assert prepared["changes"][0]["after"]["entryId"] is None
    internal._authoring(request, shown, prepared, {}, snapshot, ref, {})
    assert snapshot["tracks"]["videoTracks"] == before["tracks"]["videoTracks"]
    assert snapshot["tracks"]["audioTracks"]["layers"] == [
        before["tracks"]["audioTracks"]["layers"][0],
        before["tracks"]["audioTracks"]["layers"][2],
    ]
    assert snapshot["bmap"]["cues"] == before["bmap"]["cues"][1:]
    validate_sound_bindings(snapshot["bmap"], snapshot["tracks"])


def test_unknown_unresolved_silence_cannot_retire_another_owned_event(tmp_path):
    internal, entry, request, proposal, _, _, _, snapshot = setup(tmp_path)
    before = deepcopy(snapshot)
    request["choices"] = [
        {"eventId": "unknown", "entryId": None, "trimRange": None, "mix": None}
    ]
    request["contexts"] = []
    proposal["opportunities"] = []
    with pytest.raises(SoundPlanningError, match="current resolved opportunity"):
        internal._choices(request, proposal, {"entries": [entry]}, snapshot)
    assert snapshot == before


def test_absent_audio_cue_exception_is_limited_to_the_explicit_removed_event(tmp_path):
    _, _, request, _, _, _, _, snapshot = setup(tmp_path)
    snapshot["bmap"]["cues"].pop(0)
    with pytest.raises(ValueError, match="exact BMap audio cue"):
        validate_sound_bindings(snapshot["bmap"], snapshot["tracks"])
    validate_sound_bindings(
        snapshot["bmap"],
        snapshot["tracks"],
        removing_event_ids={request["choices"][0]["eventId"]},
    )
    with pytest.raises(ValueError, match="exact BMap audio cue"):
        validate_sound_bindings(
            snapshot["bmap"], snapshot["tracks"], removing_event_ids={"second"}
        )
