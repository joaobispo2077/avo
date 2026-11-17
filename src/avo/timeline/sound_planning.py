"""Pure source-bound candidate fits; canonical owners still publish all timing."""

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
        "visibleRange": deepcopy(opportunity["visibleRange"]),
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
    duration = sample_rate_boundary(
        trim["endSampleExclusive"] - trim["startSample"],
        source_rate=facts["sampleRate"],
        target_rate=clock["sample_rate"],
    )
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


__all__ = ["SoundPlanningError", "fit_sound_candidate"]
