"""Record independent interpretation and speech decisions for spoken notes."""

from .contracts import content_hash, validate_document
from .cutting_contracts import make_document
from .preparation_note_service import SCHEMA, note_context
from .preparation_notes import _overlaps_protection
from .store import timeline_writer


def _report(preparation, reference):
    locator = reference["locator"]
    if not locator.startswith("documents/spoken-note-report/"):
        raise ValueError("Select an immutable spoken note report")
    root = preparation.store.directory.resolve()
    path = (root / locator).resolve()
    if not path.is_relative_to(root) or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Spoken note report escapes its evidence scope")
    document = preparation.store.load_document(reference)
    if document["documentType"] != "spoken-note-report":
        raise ValueError("Select an immutable spoken note report")
    report = document["payload"]
    workspace = preparation.workspace
    if (report["videoId"], report["provider"]) != (
        workspace.video_id,
        workspace.project["provider"],
    ):
        raise ValueError("Spoken note report belongs to another project")
    return report


def _current_note(preparation, request):
    report = _report(preparation, request["reportRef"])
    context = note_context(preparation, report["input"]["analysisRef"])
    if report["binding"] != context["binding"]:
        raise ValueError("Spoken note transcript or source changed")
    matches = [note for note in report["notes"] if note["noteId"] == request["noteId"]]
    if len(matches) != 1:
        raise ValueError("Select one note from the exact reviewed report")
    return matches[0], context["protected"]


def _interpretation_effect(request, note, instructions):
    choice = request.get("interpretation")
    if choice != "accept":
        return choice
    if set(note["issues"]) - {"protected-speech"}:
        raise ValueError("Spoken note interpretation remains unresolved")
    intent = note["interpretation"]
    target = {key: intent[key] for key in ("stage", "targetId")}
    if target in instructions.get("blockedTargets", []):
        raise ValueError("Current instructions conflict with this spoken note target")
    return "pending-owner-review"


def _speech_effect(preparation, request, note, instructions, protected):
    choice = request.get("speech")
    if choice != "propose-exclusion":
        return choice, None
    if instructions.get("keepSpeech"):
        raise ValueError("Current instructions keep this spoken material")
    if note["sourceRange"] is None or set(note["issues"]) - {"target-unresolved"}:
        raise ValueError(
            "Unresolved or protected speech cannot be proposed for exclusion"
        )
    if _overlaps_protection(note["sourceRange"], protected):
        raise ValueError("Protected speech cannot become a note exclusion proposal")
    from .cutting_service import CuttingService

    proposal = CuttingService(preparation.workspace).propose_spoken_note_exclusion(note)
    return "cutting-review-required", proposal


def _result(payload, reference):
    return {
        "status": "recorded",
        "decisionRef": reference,
        "noteId": payload["note"]["noteId"],
        "interpretationEffect": payload["interpretationEffect"],
        "speechEffect": payload["speechEffect"],
        "cuttingProposalRef": payload["cuttingProposalRef"],
    }


def notes_decide(preparation, request):
    validate_document(request, SCHEMA + "noteDecisionRequest")
    digest = content_hash(request)
    with timeline_writer(preparation.workspace.timeline_dir):
        known = preparation.store.note_decision(request["operationId"])
        if known is not None:
            reference, document = known
            if document["payload"]["requestHash"] != digest:
                raise ValueError("Spoken note operation ID changes request identity")
            return _result(document["payload"], reference)
        preparation.store.require_note_choices(request)
        note, protected = _current_note(preparation, request)
        instructions = request.get("currentInstructions", {})
        interpretation = _interpretation_effect(request, note, instructions)
        speech, proposal = _speech_effect(
            preparation, request, note, instructions, protected
        )
        payload = {
            "input": request,
            "requestHash": digest,
            "note": note,
            "interpretationEffect": interpretation,
            "speechEffect": speech,
            "cuttingProposalRef": proposal,
        }
        reference = preparation.store.record_note_decision(
            make_document("spoken-note-decision", payload)
        )
        return _result(payload, reference)
