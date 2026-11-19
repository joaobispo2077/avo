"""Chunk ownership follows actual audio starts, with complete context retained."""

from copy import deepcopy

import pytest

from avo.timeline.sound_choices import freeze_sound_choices
from avo.timeline.sound_fitting import SoundPlanningError
from tests.test_sound_choices import inputs


def scope(clock, *selected):
    return {
        "clock": {
            key: deepcopy(clock[key]) for key in ("frameRate", "programEndFrame")
        },
        "chunks": [
            {"chunkId": "opening", "startFrame": 0, "endFrameExclusive": 30},
            {"chunkId": "middle", "startFrame": 30, "endFrameExclusive": 60},
            {"chunkId": "ending", "startFrame": 60, "endFrameExclusive": 90},
        ],
        "selectedChunkIds": list(selected),
    }


def frozen(tmp_path, *, frame=30, silence=False, clock=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    entry, event, choice, context, original_clock = inputs(tmp_path)
    clock = clock or original_clock
    event.update(
        programFrame=frame, visibleRange={"startFrame": 0, "endFrameExclusive": 90}
    )
    if silence:
        choice.update(entryId=None, trimRange=None, mix=None)
    return freeze_sound_choices(
        [event], [choice], entries=[entry], contexts=[context], clock=clock
    )["choices"]


def project(choices, selected, *, previous=(), clock=None):
    from avo.timeline.sound_scope import project_sound_scope

    clock = clock or choices[0]["fit"]["clock"]
    request = {
        "productionScope": scope(clock, *selected),
        "expectedBasis": dict.fromkeys(
            ("cmap", "bmap", "tracks", "animation", "sync-map")
        ),
    }
    return project_sound_scope(request, clock, choices, previous)


def test_audio_preroll_has_one_owner_before_the_visual_impact(tmp_path):
    choices = frozen(tmp_path)
    original = deepcopy(choices)
    result = project(choices, ["opening"])
    row = result["contributions"][0]
    assert row["ownerChunkId"] == "opening"
    assert row["canonicalStartFrame"] == {"num": 138, "den": 5}
    assert row["consumerChunkIds"] == ["opening"]
    assert row["current"]["endFrame"] == {"num": 258, "den": 5}
    assert row["previous"] is None
    assert result["approval"] == "not-granted"
    assert choices == original
    with pytest.raises(SoundPlanningError, match="canonical start"):
        project(choices, ["middle"])


def test_all_selected_consumers_keep_the_original_complete_audio_interval(tmp_path):
    choices = frozen(tmp_path)
    result = project(choices, ["opening", "middle"])
    assert len(result["contributions"]) == 1
    row = result["contributions"][0]
    assert row["consumerChunkIds"] == ["opening", "middle"]
    assert row["current"]["startFrame"] == row["canonicalStartFrame"]
    assert row["current"]["endFrame"] == {"num": 258, "den": 5}


def test_replacement_requires_both_old_and_new_start_owners(tmp_path):
    previous = frozen(tmp_path / "old", frame=30)
    current = frozen(tmp_path / "new", frame=60)
    with pytest.raises(SoundPlanningError, match="previous canonical start"):
        project(current, ["middle"], previous=previous)
    result = project(current, ["opening", "middle"], previous=previous)
    row = result["contributions"][0]
    assert row["ownerChunkId"] == "middle"
    assert row["previous"]["ownerChunkId"] == "opening"


def test_silence_removes_the_previous_audio_owner_instead_of_the_new_visual_owner(
    tmp_path,
):
    previous = frozen(tmp_path / "old", frame=30)
    silent = frozen(tmp_path / "new", frame=60, silence=True)
    result = project(silent, ["opening"], previous=previous)
    row = result["contributions"][0]
    assert row["ownerChunkId"] == "opening"
    assert row["current"] is None
    assert row["previous"]["startFrame"] == row["canonicalStartFrame"]
    with pytest.raises(SoundPlanningError, match="canonical start"):
        project(silent, ["middle"], previous=previous)


def test_review_scope_keeps_removed_audio_tail_and_ignores_new_silence(tmp_path):
    from avo.timeline.sound_scope import sound_review_scope

    previous = frozen(tmp_path / "old", frame=30)
    silent = frozen(tmp_path / "new", frame=60, silence=True)
    removed = project(silent, ["opening"], previous=previous)
    assert sound_review_scope(removed) == {
        "affectedChunkIds": ["opening", "middle"],
        "outsideProductionChunkIds": ["middle"],
        "approval": "not-granted",
    }

    fresh = project(silent, ["ending"])
    assert sound_review_scope(fresh)["affectedChunkIds"] == []


def test_new_explicit_silence_uses_its_visual_anchor_without_scheduling_audio(tmp_path):
    result = project(frozen(tmp_path, silence=True), ["middle"])
    row = result["contributions"][0]
    assert row["ownerChunkId"] == "middle"
    assert row["canonicalStartFrame"] == {"num": 30, "den": 1}
    assert row["current"] is row["previous"] is None


def test_fractional_clock_and_audio_sample_boundaries_are_not_rounded_to_chunks(
    tmp_path,
):
    clock = {
        "frameRate": {"num": 30000, "den": 1001},
        "sampleRate": 44100,
        "programEndFrame": 90,
    }
    choices = frozen(tmp_path, clock=clock)
    result = project(choices, ["opening"])
    from fractions import Fraction

    first = choices[0]["fit"]["event"]["scheduledAudioStartSample"]
    expected = Fraction(first * 30000, 44100 * 1001)
    assert result["contributions"][0]["canonicalStartFrame"] == {
        "num": expected.numerator,
        "den": expected.denominator,
    }
    assert expected < 30


@pytest.mark.parametrize(
    "problem", ["rate", "extent", "gap", "unknown", "duplicate", "unresolved"]
)
def test_invalid_or_unresolved_scope_never_acquires_audio_ownership(tmp_path, problem):
    from avo.timeline.sound_scope import project_sound_scope

    choices = frozen(tmp_path)
    clock = choices[0]["fit"]["clock"]
    request = {
        "productionScope": scope(clock, "opening"),
        "expectedBasis": dict.fromkeys(
            ("cmap", "bmap", "tracks", "animation", "sync-map")
        ),
    }
    if problem == "rate":
        request["productionScope"]["clock"]["frameRate"]["num"] = 25
    elif problem == "extent":
        request["productionScope"]["clock"]["programEndFrame"] = 91
        request["productionScope"]["chunks"][-1]["endFrameExclusive"] = 91
    elif problem == "gap":
        request["productionScope"]["chunks"][1]["startFrame"] += 1
    elif problem == "unknown":
        request["productionScope"]["selectedChunkIds"] = ["unknown"]
    elif problem == "duplicate":
        choices.append(deepcopy(choices[0]))
    else:
        choices[0]["fit"]["status"] = "unresolved"
    with pytest.raises(SoundPlanningError):
        project_sound_scope(request, clock, choices, [])


def test_retired_audio_with_an_incompatible_clock_requires_explicit_unscoped_removal(
    tmp_path,
):
    previous = frozen(tmp_path / "old")
    current = frozen(tmp_path / "new", silence=True)
    previous[0]["fit"]["clock"]["programEndFrame"] = 100
    with pytest.raises(SoundPlanningError, match="clock"):
        project(current, ["opening", "middle", "ending"], previous=previous)


def test_unscoped_choices_keep_their_existing_interpretation(tmp_path):
    from avo.timeline.sound_scope import project_sound_scope

    choices = frozen(tmp_path)
    assert project_sound_scope({}, choices[0]["fit"]["clock"], choices, []) is None
