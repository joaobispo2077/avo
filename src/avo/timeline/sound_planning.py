"""Pure source-bound candidate fits; canonical owners still publish all timing."""

import hashlib
import json
import math
import re
from copy import deepcopy
from fractions import Fraction

from avo.sfx_contracts import _validate_entries

from .contracts import content_hash, validate_document
from .event_clock import (
    EventClockError,
    frame_to_sample,
    resolve_timed_event,
    sample_rate_boundary,
)
from .motion_authoring import MotionAuthoringService
from .motion_review import METADATA_LIMITS, _check_budget
from .store import timeline_writer, write_immutable_json
from .tracks import apply_event_role_defaults, normalize_audio_track_layer

SCHEMA = "avo.sound-selection.schema.json"


class SoundPlanningError(ValueError):
    """Malformed fitting inputs, distinct from an unsuitable sound candidate."""


def _clock(opportunity, frame_rate, program_end_frame, sample_rate):
    validate_document(opportunity, SCHEMA + "#/$defs/opportunity")
    if not isinstance(frame_rate, Fraction) or frame_rate <= 0:
        raise SoundPlanningError(
            "Sound fitting requires a positive rational frame rate"
        )
    if type(program_end_frame) is not int or program_end_frame <= 0:
        raise SoundPlanningError(
            "Sound fitting requires the unchanged program end frame"
        )
    visible = opportunity["visibleRange"]
    if not (
        0
        <= visible["startFrame"]
        <= opportunity["programFrame"]
        < visible["endFrameExclusive"]
        <= program_end_frame
    ):
        raise SoundPlanningError(
            "Sound impact must lie in its current visible program range"
        )
    arguments = {
        "frame_rate_num": frame_rate.numerator,
        "frame_rate_den": frame_rate.denominator,
        "sample_rate": sample_rate,
    }
    return arguments, frame_to_sample(program_end_frame, **arguments)


def _candidate_issue(opportunity, entry):
    if opportunity["visibility"] != "visible":
        return "visibility-unconfirmed"
    if entry["source"]["state"] != "available" or entry["measurement"] is None:
        return "source-or-analysis-unavailable"
    if entry["measurement"]["coverage"] != "complete":
        return "analysis-coverage-incomplete"
    sha, rights = entry["source"]["sha256"], entry["rights"]
    if not all(
        (
            rights["status"] == "licensed",
            rights["sourceSha256"] == sha,
            rights["license"],
            rights["evidenceRef"],
        )
    ):
        return "source-bound-rights-required"
    marker = entry["marker"]
    if marker is None or marker["sourceSha256"] != sha:
        return "source-bound-reviewed-marker-required"
    return None


def _trim_issue(entry, trim):
    if trim is None:
        return "explicit-trim-required"
    validate_document(trim, SCHEMA + "#/$defs/sampleRange")
    first, end = trim["startSample"], trim["endSampleExclusive"]
    facts = entry["measurement"]
    if not 0 <= first < end <= facts["analyzedSamples"]:
        return "trim-outside-analyzed-source"
    if not first <= entry["marker"]["sample"] < end:
        return "marker-outside-trim"
    useful = facts["usefulRange"]
    if first > useful["startSample"] or end < useful["endSampleExclusive"]:
        return "useful-attack-or-tail-truncated"
    return None


def _source_identity(entry):
    return {
        "entryId": entry["entryId"],
        "entryRevision": entry["entryRevision"],
        "sourceSha256": entry["source"]["sha256"],
        "measurementHash": entry["measurement"]["measurementHash"],
        "annotationHash": content_hash(
            {
                key: entry[key]
                for key in ("rights", "marker", "curation", "annotationRevision")
            }
        ),
    }


def _schedule(result, entry, trim, clock, program_end_sample):
    facts, opportunity = entry["measurement"], result["opportunity"]
    event = {
        "eventId": opportunity["eventId"],
        "role": "sfx",
        "programFrame": opportunity["programFrame"],
        "visibleRange": None,
        "transientOffset": {
            "sourceSamples": entry["marker"]["sample"] - trim["startSample"],
            "sourceRate": facts["sampleRate"],
        },
    }
    try:
        resolved = resolve_timed_event(event, **clock)
    except EventClockError as error:
        result["issues"] = [str(error)]
        return
    source_clock = {
        "source_rate": facts["sampleRate"],
        "target_rate": clock["sample_rate"],
    }
    duration = sample_rate_boundary(
        trim["endSampleExclusive"], **source_clock
    ) - sample_rate_boundary(trim["startSample"], **source_clock)
    finish = resolved["scheduledAudioStartSample"] + duration
    if finish > program_end_sample:
        result["issues"] = ["insufficient-program-tail-space"]
        return
    result.update(
        status="fit",
        source=_source_identity(entry),
        trimRange=deepcopy(trim),
        event=resolved,
        scheduledAudioEndSample=finish,
    )


def fit_sound_candidate(
    opportunity, entry, *, trim_range, frame_rate, program_end_frame, sample_rate=48000
):
    """Fit a reviewed native marker without truncating sound or extending picture.

    This is metadata-only: it neither checks current file bytes nor selects or
    publishes an effect. Callers must bind the actual canonical heads and source
    generation before application, then measure and listen to encoded output.
    """
    try:
        clock, program_end_sample = _clock(
            opportunity, frame_rate, program_end_frame, sample_rate
        )
        result = {
            "contractVersion": "1.0.0",
            "clock": {
                "frameRate": {
                    "num": frame_rate.numerator,
                    "den": frame_rate.denominator,
                },
                "sampleRate": sample_rate,
                "programEndFrame": program_end_frame,
            },
            "opportunity": deepcopy(opportunity),
            "status": "silence" if entry is None else "unresolved",
            "source": None,
            "trimRange": None,
            "event": None,
            "scheduledAudioEndSample": None,
            "issues": [],
            "acceptance": "pending-listening",
        }
        if entry is not None:
            validate_document(entry, "avo.sfx-catalog.schema.json#/$defs/entry")
            _validate_entries([entry])
            issue = _candidate_issue(opportunity, entry) or _trim_issue(
                entry, trim_range
            )
            if issue:
                result["issues"] = [issue]
            else:
                _schedule(result, entry, trim_range, clock, program_end_sample)
        result["fitHash"] = content_hash(result)
        validate_document(result, SCHEMA)
        return result
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise SoundPlanningError(str(error)) from error


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


def _cue_frame(value, fps):
    base = value["timebase"]
    frame = Fraction(value["ticks"] * base["num"], base["den"]) * fps
    return sample_rate_boundary(
        frame.numerator, source_rate=frame.denominator, target_rate=1
    )


def _sound_part(item, intent):
    parts = item["parts"]
    if intent.get("cueId"):
        parts = [part for part in parts if part["cueId"] == intent["cueId"]]
    return parts[0] if len(parts) == 1 else None


def _sound_opportunity(item, part, intent, fps):
    first = _cue_frame(part["timing"]["start"], fps)
    end = _cue_frame(part["timing"]["end"], fps)
    phase = Fraction(str(intent.get("phase", 0))) * max(0, end - first - 1)
    impact = first + sample_rate_boundary(
        phase.numerator, source_rate=phase.denominator, target_rate=1
    )
    return {
        "eventId": intent["eventId"],
        "itemId": item["itemId"],
        "cueId": part["cueId"],
        "kind": intent["kind"],
        "purpose": intent["purpose"],
        "role": intent["role"],
        "visibility": intent["visibility"],
        "programFrame": impact,
        "visibleRange": {"startFrame": first, "endFrameExclusive": end},
        "material": intent.get("material"),
        "strength": intent.get("strength", "unknown"),
    }


def _sound_origin(item, part):
    cue = part["cue"]
    return {
        "cueId": part["cueId"],
        "componentRef": cue.get("componentRef")
        or (cue.get("contentRef") or {}).get("componentId")
        or item.get("componentRef"),
        "anchor": deepcopy(item["anchor"]),
        "camera": deepcopy(item.get("camera")),
    }


def _sound_recommendation(intent):
    if (
        intent.get("choice") == "silence"
        or intent["visibility"] != "visible"
        or intent["motionCharacter"] != "accent"
    ):
        return "silence"
    return "audition"


def _derive_sound_record(item, intent, fps, program_end_frame):
    record = {
        "eventId": intent["eventId"],
        "itemId": intent["itemId"],
        "intent": deepcopy(intent),
        "opportunity": None,
        "origin": None,
        "recommendation": "unresolved",
        "query": intent.get("query"),
        "silenceAllowed": True,
        "issues": [],
    }
    if item is None:
        record["issues"] = ["item-unavailable"]
        return record
    if (
        item["disposition"] == "stale"
        or item["rebaseState"] in {"removed", "ambiguous", "unsupported"}
        or item["identityConflicts"]
    ):
        record["issues"] = ["stale-or-ambiguous-origin"]
        return record
    part = _sound_part(item, intent)
    if part is None:
        record["issues"] = [
            "ambiguous-cue" if item["parts"] else "canonical-timing-required"
        ]
        return record
    opportunity = _sound_opportunity(item, part, intent, fps)
    try:
        _clock(opportunity, fps, program_end_frame, 48000)
    except (ValueError, TypeError, KeyError) as error:
        record["issues"] = ["outside-program-or-empty-cue: " + str(error)[:300]]
        return record
    record.update(
        opportunity=opportunity,
        origin=_sound_origin(item, part),
        recommendation=_sound_recommendation(intent),
    )
    return record


def derive_sound_opportunities(snapshot, intents, *, frame_rate, program_end_frame):
    """Derive only requested sound events from current metadata, with silence valid.

    Visibility, material and strength remain declared editorial intent. This does
    not inspect media, infer word timing, search a library or publish an effect.
    """
    try:
        validate_document(snapshot, "avo.motion-review.schema.json")
        validate_document(intents, SCHEMA + "#/$defs/intents")
        if not isinstance(frame_rate, Fraction):
            raise SoundPlanningError(
                "Opportunity derivation requires a positive rational program clock"
            )
        validate_document(
            {
                "frameRate": {
                    "num": frame_rate.numerator,
                    "den": frame_rate.denominator,
                },
                "sampleRate": 48000,
                "programEndFrame": program_end_frame,
            },
            SCHEMA + "#/$defs/candidateFit/properties/clock",
        )
        ids = [intent["eventId"] for intent in intents]
        if len(set(ids)) != len(ids):
            raise SoundPlanningError("Sound event IDs must be unique")
        items = {item["itemId"]: item for item in snapshot["items"]}
        records = [
            _derive_sound_record(
                items.get(intent["itemId"]), intent, frame_rate, program_end_frame
            )
            for intent in intents
        ]
        for record in records:
            validate_document(record, SCHEMA + "#/$defs/opportunityRecord")
        return records
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise SoundPlanningError(str(error)) from error


def _sound_document(value, definition):
    _check_budget(value, METADATA_LIMITS)
    validate_document(value, SCHEMA + "#/$defs/" + definition)
    if len(json.dumps(value, allow_nan=False).encode("utf-8")) > 4 * 1024 * 1024:
        raise SoundPlanningError("Sound proposal exceeds the 4 MiB metadata budget")
    return deepcopy(value)


class SoundPlanningService:
    """Explicit proposal writes; construction never scans, renders or approves."""

    def __init__(self, workspace, *, catalogue):
        self.workspace, self.catalogue = workspace, catalogue
        self.authoring = MotionAuthoringService(workspace)
        self.root = workspace.raw_dir / "edit/motion/sound"
        if not self.root.resolve().is_relative_to(workspace.raw_dir.resolve()):
            raise SoundPlanningError("Sound proposal path escapes the project")
        if catalogue.workspace.raw_dir.resolve() != workspace.raw_dir.resolve():
            raise SoundPlanningError("Sound catalogue belongs to another project")

    def _path(self, collection, identity):
        path = self.root / collection / (identity + ".json")
        if not path.resolve().is_relative_to(self.workspace.raw_dir.resolve()):
            raise SoundPlanningError("Sound metadata escapes project containment")
        return path

    def load(self, digest):
        if not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest):
            raise SoundPlanningError("Exact sound proposal SHA-256 required")
        path = self._path("proposals", digest)
        value, raw = self.authoring._read(path)
        _sound_document(value, "proposal")
        if (
            hashlib.sha256(raw).hexdigest() != digest
            or content_hash({k: v for k, v in value.items() if k != "proposalHash"})
            != value["proposalHash"]
        ):
            raise SoundPlanningError("Immutable sound proposal changed")
        if (
            value["videoId"] != self.workspace.video_id
            or value["provider"] != self.workspace.project["provider"]
        ):
            raise SoundPlanningError("Sound proposal belongs to another project")
        return {
            "operation": "propose",
            "status": "proposed",
            "proposal": value,
            "proposalRef": self.authoring._ref(path, raw),
        }

    def _known(self, request):
        path = self._path(
            "operations", content_hash(["propose", request["operationId"]])
        )
        if not path.exists():
            return None
        record, _ = self.authoring._read(path)
        _sound_document(record, "operationRecord")
        if (
            record["requestHash"] != content_hash(request)
            or record["request"] != request
        ):
            raise SoundPlanningError(
                "Sound operation identity records different inputs"
            )
        result = self.load(record["proposalRef"]["sha256"])
        if (
            result["proposalRef"] != record["proposalRef"]
            or result["proposal"]["requestHash"] != record["requestHash"]
        ):
            raise SoundPlanningError("Sound proposal differs from its actual request")
        return result

    def _program_clock(self, clock):
        from .bmap_service import BMapService
        from .mapping import cmap_output_duration, cmap_output_timebase

        if self.workspace.authority != "canonical":
            raise SoundPlanningError("Sound proposals require a canonical approved cut")
        _, cmap, _ = BMapService(self.workspace).current_basis()
        base = cmap_output_timebase(cmap["snapshot"])
        fps = Fraction(clock["frameRate"]["num"], clock["frameRate"]["den"])
        extent = (
            Fraction(cmap_output_duration(cmap["snapshot"]) * base["num"], base["den"])
            * fps
        )
        if extent != clock["programEndFrame"]:
            raise SoundPlanningError(
                "Sound clock differs from the approved program extent"
            )
        return fps

    def _match(self, records, generation, mode, budget, filters):
        used = 0
        for record in records:
            record["search"] = None
            if record["recommendation"] != "audition":
                continue
            if not record["query"]:
                record["issues"].append("query-required")
            elif used >= budget:
                record["issues"].append("candidate-budget-exhausted")
            else:
                record["search"] = self.catalogue.search(
                    record["query"],
                    filters=filters,
                    limit=min(20, budget - used),
                    generation=generation,
                    mode=mode,
                )
                used += len(record["search"]["results"])
        return used

    def _direction(self, request):
        from avo.direction.brief import BriefService

        current = self.authoring._direction_ref()
        frozen = ((self.authoring._run() or {}).get("executionChoices") or {}).get(
            "editingCraft"
        )
        if (
            frozen
            and not request.get("newRequest")
            and request.get("requestId") is None
            and frozen["directionRef"] != current
        ):
            raise SoundPlanningError(
                "Frozen direction changed; select an explicit new request"
            )
        context = (
            None
            if current is None
            else BriefService(self.workspace.project_path).stage_context(
                "sound", record=False
            )["context"]
        )
        if self.authoring._direction_ref() != current:
            raise SoundPlanningError("Direction changed while proposing sound")
        return current, context

    def _draft_request_id(self, request):
        previous = ((self.authoring._run() or {}).get("executionChoices") or {}).get(
            "editingCraft"
        )
        if (
            previous
            and not request.get("newRequest")
            and request.get("requestId") is None
        ):
            return previous["requestId"]
        return (
            request.get("requestId")
            or "craft-" + content_hash(request["operationId"])[:24]
        )

    def _propose(self, request):
        from .pipeline import TimelinePipeline

        snapshot = TimelinePipeline(self.workspace).motion_plan()
        self.authoring._check_heads(request["expectedBasis"])
        selection = self.authoring._proposal_selection(request)
        matching = selection["effective"]["soundMatching"]
        if not matching["enabled"]:
            raise SoundPlanningError(
                "Sound matching requires explicitly selected options"
            )
        fps = self._program_clock(request["clock"])
        generation = self.catalogue.show()["generationId"]
        if request["expectedGeneration"] != generation:
            raise SoundPlanningError("Sound catalogue generation changed")
        direction_ref, direction = self._direction(request)
        records = derive_sound_opportunities(
            snapshot,
            request["intents"],
            frame_rate=fps,
            program_end_frame=request["clock"]["programEndFrame"],
        )
        budget = request.get("maxCandidates", 100)
        used = self._match(
            records,
            generation,
            matching["mode"],
            budget,
            request.get("filters", {"rights": ["licensed"]}),
        )
        if (
            self.catalogue.show()["generationId"] != generation
            or self.authoring._direction_ref() != direction_ref
        ):
            raise SoundPlanningError(
                "Catalogue or direction changed while proposing sound"
            )
        self.authoring._check_heads(request["expectedBasis"])
        proposal = {
            "contractVersion": "1.0.0",
            "operationId": request["operationId"],
            "requestHash": content_hash(request),
            "requestId": self._draft_request_id(request),
            "provider": self.workspace.project["provider"],
            "videoId": self.workspace.video_id,
            "basisHeads": request["expectedBasis"],
            "options": selection,
            "directionRef": direction_ref,
            "direction": direction,
            "clock": request["clock"],
            "generationId": generation,
            "opportunities": records,
            "coverage": {
                "intents": len(records),
                "candidates": used,
                "candidateBudget": budget,
            },
        }
        proposal["proposalHash"] = content_hash(proposal)
        proposal = _sound_document(proposal, "proposal")
        frozen = self.authoring._freeze(request)
        if (frozen["requestId"], frozen["selection"]) != (
            proposal["requestId"],
            proposal["options"],
        ):
            raise SoundPlanningError("Frozen sound request changed during publication")
        return proposal

    def propose(self, request):
        try:
            request = _sound_document(request, "proposeRequest")
            with timeline_writer(self.workspace.timeline_dir):
                known = self._known(request)
                if known is not None:
                    return known
                proposal = self._propose(request)
                raw = (
                    json.dumps(proposal, indent=2, ensure_ascii=False, sort_keys=True)
                    + "\n"
                ).encode("utf-8")
                digest = hashlib.sha256(raw).hexdigest()
                path = self._path("proposals", digest)
                write_immutable_json(path, proposal)
                reference = self.authoring._ref(path, raw)
                record = {
                    "requestHash": content_hash(request),
                    "request": request,
                    "proposalRef": reference,
                }
                _sound_document(record, "operationRecord")
                write_immutable_json(
                    self._path(
                        "operations", content_hash(["propose", request["operationId"]])
                    ),
                    record,
                )
                return self.load(digest)
        except (ValueError, TypeError, KeyError, OSError) as error:
            raise SoundPlanningError(str(error)) from error


__all__ = [
    "SoundPlanningError",
    "SoundPlanningService",
    "derive_sound_opportunities",
    "fit_sound_candidate",
    "freeze_sound_choices",
]
