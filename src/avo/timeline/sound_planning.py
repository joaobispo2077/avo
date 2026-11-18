"""Bounded motion-bound sound proposals and explicit per-event choices."""

import hashlib
import json
import re
from copy import deepcopy
from fractions import Fraction

from . import sound_choices as _sound_choices
from .contracts import content_hash, validate_document
from .craft_work import remember_craft_proposal
from .event_clock import (
    sample_rate_boundary,
)
from .motion_authoring import MotionAuthoringService
from .sound_choices import _sound_document, freeze_sound_choices
from .sound_fitting import SCHEMA, SoundPlanningError, _clock, fit_sound_candidate
from .store import timeline_writer, write_immutable_json

_previous_sound_choices = _sound_choices._previous_sound_choices


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


class SoundPlanningService:
    """Explicit proposal writes; construction never scans, renders or approves."""

    def __init__(self, workspace, *, catalogue, source_probe=None):
        self.workspace, self.catalogue = workspace, catalogue
        self.source_probe = source_probe
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
        self._verify_proposal_operation(value, self.authoring._ref(path, raw))
        return {
            "operation": "propose",
            "status": "proposed",
            "proposal": value,
            "proposalRef": self.authoring._ref(path, raw),
        }

    def _verify_proposal_operation(self, proposal, reference):
        path = self._path(
            "operations", content_hash(["propose", proposal["operationId"]])
        )
        record, _ = self.authoring._read(path)
        record = _sound_document(record, "operationRecord")
        request = _sound_document(record["request"], "proposeRequest")
        bindings = {
            "operationId": "operationId",
            "requestHash": None,
            "basisHeads": "expectedBasis",
            "generationId": "expectedGeneration",
            "clock": "clock",
        }
        expected_hash = content_hash(request)
        if record["proposalRef"] != reference or record["requestHash"] != expected_hash:
            raise SoundPlanningError("Sound proposal operation/reference changed")
        for key, request_key in bindings.items():
            expected = expected_hash if request_key is None else request[request_key]
            if proposal[key] != expected:
                raise SoundPlanningError(
                    "Sound proposal differs from its actual operation request"
                )

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
        from .program_clock import ProgramClockError, require_program_clock

        try:
            return require_program_clock(self.workspace, clock, subject="Sound")
        except ProgramClockError as error:
            raise SoundPlanningError(str(error)) from error

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

    def apply(self, request):
        from .sound_application import apply_sound_request

        return self._with_review(apply_sound_request(self, request))

    def _with_review(self, result):
        from .motion_review import MotionReviewService
        from .pipeline import TimelinePipeline

        try:
            shown = self.load(result["proposalRef"]["sha256"])
            snapshot = TimelinePipeline(self.workspace).motion_plan(
                sound_proposal={
                    "proposal": shown["proposal"],
                    "proposalRef": shown["proposalRef"],
                }
            )
            result["review"] = MotionReviewService(self.workspace).publish(
                snapshot, expected_basis=snapshot["basisHeads"]
            )
            result["reviewReady"] = result["review"]["status"] == "published"
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            result["reviewReady"] = False
            result.setdefault("warnings", []).append(
                f"Current sound presentation unavailable: {error}"
            )
        return result

    def propose(self, request):
        try:
            request = _sound_document(request, "proposeRequest")
            with timeline_writer(self.workspace.timeline_dir):
                known = self._known(request)
                if known is not None:
                    return self._with_review(
                        remember_craft_proposal(self.workspace, "sound", known)
                    )
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
                return self._with_review(
                    remember_craft_proposal(self.workspace, "sound", self.load(digest))
                )
        except (ValueError, TypeError, KeyError, OSError) as error:
            raise SoundPlanningError(str(error)) from error


__all__ = [
    "SoundPlanningError",
    "SoundPlanningService",
    "derive_sound_opportunities",
    "fit_sound_candidate",
    "freeze_sound_choices",
]
