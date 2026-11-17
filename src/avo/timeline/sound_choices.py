"""Bounded data-only sound choice fitting, mix validation and revision reports."""

import json
import math
from copy import deepcopy
from fractions import Fraction

from avo.sfx_contracts import _validate_entries

from .contracts import content_hash, validate_document
from .event_clock import sample_rate_boundary
from .motion_metadata import METADATA_LIMITS, _check_budget
from .sound_fitting import SCHEMA, SoundPlanningError, fit_sound_candidate
from .track_rules import apply_event_role_defaults, normalize_audio_track_layer


def _unique_sound_ids(values, key):
    result = {value[key]: value for value in values}
    if len(result) != len(values):
        raise SoundPlanningError("Sound identities must be unique: " + key)
    return result


def _check_choice_mix(entry, fit, mix):
    normalize_audio_track_layer({"role": "sfx", **mix})
    facts = entry["measurement"]
    channels = {"mono": 1, "stereo": 2}[mix["sourceLayout"]]
    if facts["channels"] != channels:
        raise SoundPlanningError("Selected channel layout differs from measured source")
    peak = facts["peak"]
    if peak == 0 or facts["silence"]:
        raise SoundPlanningError("Selected sound has no measured audible signal")
    if 20 * math.log10(peak) + mix["gainDb"] > mix["peakCeilingDbfs"] + 1e-9:
        raise SoundPlanningError("Sound gain exceeds its explicit source peak ceiling")
    trim, useful = fit["trimRange"], facts["usefulRange"]
    clock = {
        "source_rate": facts["sampleRate"],
        "target_rate": fit["clock"]["sampleRate"],
    }
    leading = sample_rate_boundary(
        useful["startSample"], **clock
    ) - sample_rate_boundary(trim["startSample"], **clock)
    trailing = sample_rate_boundary(
        trim["endSampleExclusive"], **clock
    ) - sample_rate_boundary(useful["endSampleExclusive"], **clock)
    if mix["fadeInSamples"] > leading or mix["fadeOutSamples"] > trailing:
        raise SoundPlanningError("Sound fade would alter the useful attack or tail")


def _fit_choice(opportunity, entry, trim, clock):
    rate = clock["frameRate"]
    return fit_sound_candidate(
        opportunity,
        entry,
        trim_range=trim,
        frame_rate=Fraction(rate["num"], rate["den"]),
        program_end_frame=clock["programEndFrame"],
        sample_rate=clock["sampleRate"],
    )


def _freeze_sound_choice(opportunities, entries, choice, clock):
    event = opportunities.get(choice["eventId"])
    if event is None:
        raise SoundPlanningError("Sound choice has no current proposed event")
    entry = None if choice["entryId"] is None else entries.get(choice["entryId"])
    if choice["entryId"] is not None and entry is None:
        raise SoundPlanningError("Sound choice has no selected catalogue entry")
    fit = _fit_choice(event, entry, choice["trimRange"], clock)
    if fit["status"] == "fit":
        _check_choice_mix(entry, fit, choice["mix"])
    result = {
        "eventId": event["eventId"],
        "itemId": event["itemId"],
        "fit": fit,
        "mix": deepcopy(choice["mix"]),
        "sourceEntry": deepcopy(entry),
        "acceptance": "pending-listening",
    }
    result["choiceHash"] = content_hash(result)
    return _sound_document(result, "frozenChoice")


def _check_sound_roles(choices, contexts):
    groups = {}
    for choice in choices:
        if choice["fit"]["status"] == "fit":
            cue_id = choice["fit"]["opportunity"]["cueId"]
            groups.setdefault(cue_id, []).append(choice["eventId"])
    for cue_id, events in groups.items():
        context = contexts.get(cue_id)
        if context is None:
            raise SoundPlanningError("Current owning visual role is required for sound")
        ordered = context["orderedEventIds"]
        if ordered and ordered != events:
            raise SoundPlanningError(
                "Ordered sound layers differ from exact selected events"
            )
        normalized = apply_event_role_defaults(
            {
                "role": context["role"],
                "entryEffectIds": events,
                "orderedMultiEffect": bool(ordered),
                "syntheticEffectApproved": context["syntheticEffectApproved"],
            }
        )
        if normalized.get("render") is False:
            raise SoundPlanningError("Comparison-only references cannot publish sound")


def _sound_choice_advisories(choices):
    groups = {"repeated-source": {}, "colliding-attacks": {}}
    for choice in choices:
        fit = choice["fit"]
        if fit["status"] != "fit":
            continue
        values = {
            "repeated-source": fit["source"]["sourceSha256"],
            "colliding-attacks": fit["event"]["resolvedImpactSample"],
        }
        for code, key in values.items():
            groups[code].setdefault(key, []).append(choice["eventId"])
    return [
        {"code": code, "eventIds": identities}
        for code, grouped in groups.items()
        for identities in grouped.values()
        if len(identities) > 1
    ]


def _sound_choice_summary(choice):
    if choice is None:
        return None
    fit, mix = choice["fit"], choice["mix"]
    return {
        "sourceSha256": (fit["source"] or {}).get("sourceSha256"),
        "entryId": (fit["source"] or {}).get("entryId"),
        "entryRevision": (fit["source"] or {}).get("entryRevision"),
        "annotationHash": (fit["source"] or {}).get("annotationHash"),
        "role": fit["opportunity"]["role"],
        "gainDb": None if mix is None else mix["gainDb"],
        "schedule": fit["event"],
        "endSampleExclusive": fit["scheduledAudioEndSample"],
    }


def _previous_sound_choices(previous):
    previous = _sound_document(previous, "frozenChoices")
    for choice in previous:
        fit = choice["fit"]
        inputs = {
            "eventId": choice["eventId"],
            "entryId": None
            if choice["sourceEntry"] is None
            else choice["sourceEntry"]["entryId"],
            "trimRange": fit["trimRange"],
            "mix": choice["mix"],
        }
        if fit["status"] == "unresolved":
            raise SoundPlanningError("Unresolved fits cannot confer previous selection")
        reconstructed = _freeze_sound_choice(
            {choice["eventId"]: fit["opportunity"]},
            {}
            if choice["sourceEntry"] is None
            else {inputs["entryId"]: choice["sourceEntry"]},
            inputs,
            fit["clock"],
        )
        if reconstructed != choice:
            raise SoundPlanningError("Previous sound choice identity changed")
    return _unique_sound_ids(previous, "eventId")


def freeze_sound_choices(
    opportunities, choices, *, entries, contexts, clock, previous=None
):
    """Prepare explicit per-event metadata, never source reads or canonical writes.

    The caller owns current proposal/head/catalogue membership checks. This pure
    boundary binds supplied validated entries and the reviewed marker to actual
    fitting/mix settings. It does not measure the combined mix or approve it.
    """
    try:
        events = _sound_document(opportunities, "choiceOpportunities")
        choices = _sound_document(choices, "choiceInputs")
        entries = _sound_document(entries, "choiceEntries")
        contexts = _sound_document(contexts, "soundContexts")
        validate_document(clock, SCHEMA + "#/$defs/candidateFit/properties/clock")
        _validate_entries(entries)
        events = _unique_sound_ids(events, "eventId")
        _unique_sound_ids(choices, "eventId")
        entry_map = _unique_sound_ids(entries, "entryId")
        context_map = _unique_sound_ids(contexts, "cueId")
        before = _previous_sound_choices(previous or [])
        prepared = [
            _freeze_sound_choice(events, entry_map, choice, clock) for choice in choices
        ]
        _check_sound_roles(prepared, context_map)
        return {
            "choices": prepared,
            "changes": [
                {
                    "eventId": c["eventId"],
                    "before": _sound_choice_summary(before.get(c["eventId"])),
                    "after": _sound_choice_summary(c),
                }
                for c in prepared
            ],
            "advisories": _sound_choice_advisories(prepared),
            "reviewObligations": [
                "current-source-and-catalogue",
                "combined-peak",
                "dialogue-masking",
                "contextual-listening",
            ],
            "acceptance": "pending-listening",
        }
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise SoundPlanningError(str(error)) from error


def _sound_document(value, definition):
    _check_budget(value, METADATA_LIMITS)
    validate_document(value, SCHEMA + "#/$defs/" + definition)
    if len(json.dumps(value, allow_nan=False).encode("utf-8")) > 4 * 1024 * 1024:
        raise SoundPlanningError("Sound proposal exceeds the 4 MiB metadata budget")
    return deepcopy(value)
