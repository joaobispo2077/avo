"""Publish source-bound note review evidence through the existing cutting store."""

from pathlib import Path

from avo.editing_craft import validate_editing_craft_selection

from .contracts import content_hash, file_fingerprint, validate_document
from .cutting_contracts import make_document
from .preparation import inspect_speech_coverage
from .preparation_notes import _delimiters, detect_spoken_notes
from .store import timeline_writer

SCHEMA = "avo.preparation.schema.json#/$defs/"


def _verify_note_source(source_ref):
    locator = source_ref["locator"]
    path = Path(locator)
    if not path.is_absolute() or locator.startswith(("//", "\\\\")):
        raise ValueError("Spoken notes require a current local source")
    if file_fingerprint(path)["sha256"] != source_ref["sha256"]:
        raise ValueError("Spoken note source bytes changed")


def note_context(preparation, analysis_ref):
    original = preparation._analysis(analysis_ref)
    source_range = preparation._original_range(original)
    snapshot, source, routing, sync_ref = preparation._canonical_source(source_range)
    source_ref = {
        "locator": source["locator"],
        "sha256": source["fingerprint"]["sha256"],
    }
    if original["sourceRef"] != source_ref:
        raise ValueError("Spoken note evidence belongs to different source bytes")
    _verify_note_source(source_ref)
    current = preparation.source_evidence(
        source, source_range=source_range, routing=routing, sync_ref=sync_ref
    )
    current_ref = current["originalAnalysisRef"]
    if current_ref is not None and current_ref != analysis_ref:
        raise ValueError("Selected original transcript changed before note review")
    analysis = current["analysis"] or original
    coverage = inspect_speech_coverage(
        analysis,
        source_ref=source_ref,
        source_range=source_range,
        routing=routing,
        sync_ref=sync_ref,
    )
    binding = {
        "sourceRef": source_ref,
        "sourceRange": source_range,
        "routingHash": content_hash(routing),
        "syncRef": sync_ref,
        "transcriptSelectionHash": current["selectionHash"],
        "wordsHash": content_hash(
            {key: analysis.get(key) for key in ("language", "alignment", "words")}
        ),
    }
    return {
        "analysis": analysis,
        "snapshot": snapshot,
        "binding": binding,
        "protected": [*coverage["protectedRanges"], *current["protectedRanges"]],
    }


def notes_detect(preparation, request):
    validate_document(request, SCHEMA + "notesDetectRequest")
    policy = validate_editing_craft_selection(request["selection"])["effective"][
        "spokenNotes"
    ]
    if (
        not policy["enabled"]
        or not request["targets"]
        or not _delimiters(policy)
        or not policy.get("language")
    ):
        return {
            "status": "disabled",
            "notes": [],
            "issues": ["convention-unselected"],
            "truncated": False,
        }
    workspace = preparation.workspace
    with timeline_writer(workspace.timeline_dir):
        context = note_context(preparation, request["analysisRef"])
        result = detect_spoken_notes(
            context["analysis"],
            context["binding"]["sourceRange"],
            policy=policy,
            targets=request["targets"],
            protected=context["protected"],
        )
        for note in result["notes"]:
            note["noteId"] = (
                "note-"
                + content_hash(
                    {
                        "candidate": note["noteId"],
                        "sourceSha256": context["binding"]["sourceRef"]["sha256"],
                    }
                )[:24]
            )
        payload = {
            "input": request,
            "binding": context["binding"],
            "provider": workspace.project["provider"],
            "videoId": workspace.video_id,
            **result,
        }
        reference = preparation.store.save_document(
            make_document("spoken-note-report", payload)
        )
    return {**result, "reportRef": reference}
