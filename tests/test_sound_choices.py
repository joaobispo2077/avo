"""Per-event choices bind reviewed assets without relaxing existing sound limits."""

from copy import deepcopy

import pytest

from avo.timeline.sound_planning import SoundPlanningError, freeze_sound_choices
from tests.test_sound_planning import candidate, opportunity


def inputs(tmp_path):
    entry = candidate(tmp_path)
    event = opportunity()
    choice = {
        "eventId": event["eventId"],
        "entryId": entry["entryId"],
        "trimRange": {"startSample": 0, "endSampleExclusive": 48000},
        "mix": {
            "sourceLayout": "stereo",
            "targetLayout": "stereo",
            "channelMap": [0, 1],
            "gainDb": -12,
            "peakCeilingDbfs": -3,
            "fadeInSamples": 0,
            "fadeOutSamples": 0,
            "ducking": None,
        },
    }
    context = {
        "cueId": event["cueId"],
        "role": "authored-graphic",
        "orderedEventIds": [],
        "syntheticEffectApproved": False,
    }
    clock = {
        "frameRate": {"num": 24, "den": 1},
        "sampleRate": 48000,
        "programEndFrame": 90,
    }
    return entry, event, choice, context, clock


def prepare(entry, events, choices, contexts, clock, **kwargs):
    return freeze_sound_choices(
        events, choices, entries=[entry], contexts=contexts, clock=clock, **kwargs
    )


def test_choice_freezes_source_marker_rights_mix_and_exact_schedule(tmp_path):
    entry, event, choice, context, clock = inputs(tmp_path)
    original = deepcopy((entry, event, choice))
    result = prepare(entry, [event], [choice], [context], clock)
    selected = result["choices"][0]
    assert selected["fit"]["status"] == "fit"
    assert selected["sourceEntry"] == entry
    assert selected["mix"] == choice["mix"]
    assert selected["acceptance"] == "pending-listening"
    assert selected["fit"]["event"]["resolvedImpactSample"] == 60000
    assert result["changes"][0]["before"] is None
    assert (entry, event, choice) == original


@pytest.mark.parametrize("role", ["main", "bass", "support", "detail", "tail"])
def test_named_sound_role_cannot_bypass_ordinary_overlay_entry_limit(tmp_path, role):
    entry, event, choice, context, clock = inputs(tmp_path)
    second = {**event, "eventId": "second", "role": role}
    with pytest.raises(SoundPlanningError, match="one entry SFX"):
        prepare(
            entry,
            [event, second],
            [choice, {**choice, "eventId": "second"}],
            [context],
            clock,
        )


def test_ordered_layering_is_explicit_and_repetition_and_attacks_are_reported(tmp_path):
    entry, event, choice, context, clock = inputs(tmp_path)
    context["orderedEventIds"] = [event["eventId"], "second"]
    result = prepare(
        entry,
        [event, {**event, "eventId": "second", "role": "tail"}],
        [choice, {**choice, "eventId": "second"}],
        [context],
        clock,
    )
    assert [c["eventId"] for c in result["choices"]] == context["orderedEventIds"]
    assert {a["code"] for a in result["advisories"]} == {
        "repeated-source",
        "colliding-attacks",
        "overlapping-sounds",
    }
    assert all(c["acceptance"] == "pending-listening" for c in result["choices"])


def test_main_scene_requires_explicit_synthetic_effect_disposition(tmp_path):
    entry, event, choice, context, clock = inputs(tmp_path)
    context["role"] = "main-scene"
    with pytest.raises(SoundPlanningError, match="main-scene"):
        prepare(entry, [event], [choice], [context], clock)
    context["syntheticEffectApproved"] = True
    assert (
        prepare(entry, [event], [choice], [context], clock)["choices"][0]["fit"][
            "status"
        ]
        == "fit"
    )


@pytest.mark.parametrize(
    "problem",
    ["channel", "source-layout", "peak", "fade", "unknown-event", "duplicate"],
)
def test_invalid_mix_and_identity_choices_do_not_become_prepared_sounds(
    tmp_path, problem
):
    entry, event, choice, context, clock = inputs(tmp_path)
    choices = [choice]
    if problem == "channel":
        choice["mix"]["channelMap"] = [0, 2]
    elif problem == "source-layout":
        choice["mix"]["sourceLayout"] = "mono"
        choice["mix"]["channelMap"] = [0, 0]
    elif problem == "peak":
        choice["mix"]["gainDb"] = 12
    elif problem == "fade":
        choice["mix"]["fadeInSamples"] = 10000
    elif problem == "unknown-event":
        choice["eventId"] = "not-proposed"
    else:
        choices.append(deepcopy(choice))
    with pytest.raises(SoundPlanningError):
        prepare(entry, [event], choices, [context], clock)


def test_silence_and_single_id_revision_report_before_after_without_touching_other_choices(
    tmp_path,
):
    entry, event, choice, context, clock = inputs(tmp_path)
    first = prepare(entry, [event], [choice], [context], clock)
    silent = {
        "eventId": event["eventId"],
        "entryId": None,
        "trimRange": None,
        "mix": None,
    }
    result = prepare(
        entry, [event], [silent], [context], clock, previous=first["choices"]
    )
    assert result["choices"][0]["fit"]["status"] == "silence"
    assert result["choices"][0]["sourceEntry"] is None
    assert result["changes"][0]["before"]["sourceSha256"] == entry["source"]["sha256"]
    assert result["changes"][0]["after"]["sourceSha256"] is None
    ranges = result["changes"][0]["listeningRanges"]
    assert (
        ranges["before"]["startSample"]
        == first["choices"][0]["fit"]["event"]["scheduledAudioStartSample"]
    )
    assert ranges["after"] is None
    assert first["choices"][0]["mix"]["gainDb"] == -12


def test_revised_level_reports_only_its_requested_event_and_preserves_exact_asset_identity(
    tmp_path,
):
    entry, event, choice, context, clock = inputs(tmp_path)
    first = prepare(entry, [event], [choice], [context], clock)
    choice["mix"]["gainDb"] = -18
    result = prepare(
        entry, [event], [choice], [context], clock, previous=first["choices"]
    )
    change = result["changes"][0]
    assert change["before"]["entryId"] == change["after"]["entryId"] == entry["entryId"]
    assert change["before"]["gainDb"] == -12 and change["after"]["gainDb"] == -18
    assert change["before"]["schedule"] == change["after"]["schedule"]
    assert "dialogue-masking" in result["reviewObligations"]
    assert first["choices"][0]["choiceHash"] != result["choices"][0]["choiceHash"]


def test_resealed_previous_choice_cannot_confer_a_changed_marker_review(tmp_path):
    from avo.timeline.contracts import content_hash

    entry, event, choice, context, clock = inputs(tmp_path)
    previous = prepare(entry, [event], [choice], [context], clock)["choices"]
    previous[0]["sourceEntry"]["marker"]["reviewerRef"] = "changed-review"
    previous[0]["choiceHash"] = content_hash(
        {k: v for k, v in previous[0].items() if k != "choiceHash"}
    )
    with pytest.raises(SoundPlanningError, match="Previous sound choice identity"):
        prepare(entry, [event], [choice], [context], clock, previous=previous)
