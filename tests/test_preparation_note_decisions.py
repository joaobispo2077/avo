"""Spoken note review separates editorial intent from a proposed speech exclusion."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.cli import main
from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.contracts import file_fingerprint
from avo.timeline.cutting_contracts import make_document
from avo.timeline.iterations import pending_stage_notes
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.preparation_recovery import PreparationService
from tests.test_preparation_notes import POLICY, TARGETS, transcript
from tests.test_speech_recovery import recovery


def prepared_note(tmp_path, *, protected=False):
    cutting, _, preparation, _, base = recovery(tmp_path)
    workspace = preparation.workspace
    workspace.project["cutting"] = {"enabled": True, "family": "tutorial"}
    workspace.project_path.write_text(json.dumps(workspace.project), encoding="utf-8")
    analysis = deepcopy(preparation._analysis(base["analysisRef"]))
    words = transcript("Editor note: Opening graphic hold longer. End note.")["words"]
    for word in words:
        word["alignmentStatus"] = "aligned"
    analysis.update(
        language="en",
        words=words,
        alignment={"status": "pass", "characters": []},
        status="pass",
        coverage={"observed": True, "start": 0, "end": 0.2 if protected else 1},
        vad=[{"start": 0, "end": 0.8}],
    )
    reference = preparation.store.save_document(
        make_document("source-analysis", analysis)
    )
    request = {
        "contractVersion": "1.0.0",
        "operation": "notes-detect",
        "analysisRef": reference,
        "selection": resolve_editing_craft_selection(
            invocation={"spokenNotes": POLICY}
        ),
        "targets": TARGETS,
    }
    return cutting, preparation, request


def note_request(report, operation_id, **overrides):
    return {
        "contractVersion": "1.0.0",
        "operation": "notes-decide",
        "operationId": operation_id,
        "actor": "creator",
        "reason": "Review this recorded production note",
        "reportRef": report["reportRef"],
        "noteId": report["notes"][0]["noteId"],
        **overrides,
    }


def test_native_detection_and_independent_decisions_never_apply_a_cut(tmp_path, capsys):
    cutting, preparation, request = prepared_note(tmp_path)
    workspace = preparation.workspace
    source = Path(preparation._analysis(request["analysisRef"])["sourceRef"]["locator"])
    original = file_fingerprint(source)["sha256"]
    cmap_before = workspace.store("cmap").load()
    path = tmp_path / "spoken-note-request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    command = [
        "preparation",
        "notes-detect",
        "--project",
        str(workspace.project_path),
        "--video-id",
        workspace.video_id,
        "--request",
        str(path),
        "--json",
    ]
    assert main([*command, "--request-sha256", "f" * 64]) != 0
    capsys.readouterr()
    assert main([*command, "--request-sha256", file_fingerprint(path)["sha256"]]) == 0
    report = json.loads(capsys.readouterr().out)
    note = report["notes"][0]
    assert note["status"] == "candidate", note
    assert note["sourceRange"]["endTicksExclusive"] == 38_400
    interpret = note_request(
        report,
        "interpret-note",
        interpretation="accept",
        expectedInterpretationRef=None,
    )
    path.write_text(json.dumps(interpret), encoding="utf-8")
    command[1] = "notes-decide"
    assert main([*command, "--request-sha256", file_fingerprint(path)["sha256"]]) == 0
    selected = json.loads(capsys.readouterr().out)
    assert selected["interpretationEffect"] == "pending-owner-review"
    assert selected["speechEffect"] is None
    assert selected["cuttingProposalRef"] is None
    preparation = PreparationService(workspace)
    assert preparation.notes_decide(interpret) == selected
    exclusion = note_request(
        report, "propose-exclusion", speech="propose-exclusion", expectedSpeechRef=None
    )
    result = preparation.notes_decide(exclusion)
    assert result["interpretationEffect"] is None
    assert result["speechEffect"] == "cutting-review-required"
    proposal = cutting.store.load_document(result["cuttingProposalRef"])["payload"]
    assert any(
        edit["removeRange"] == note["sourceRange"] and edit["editorialApprovalRequired"]
        for edit in proposal["edits"]
    )
    assert workspace.store("cmap").load() == cmap_before
    assert file_fingerprint(source)["sha256"] == original


def test_current_instructions_and_protected_speech_win_without_canonical_writes(
    tmp_path,
):
    _, preparation, request = prepared_note(tmp_path, protected=True)
    report = preparation.notes_detect(request)
    assert "protected-speech" in report["notes"][0]["issues"]
    interpret = note_request(
        report,
        "blocked-interpretation",
        interpretation="accept",
        expectedInterpretationRef=None,
        currentInstructions={
            "blockedTargets": [{"stage": "motion", "targetId": "opening-title"}]
        },
    )
    with pytest.raises(ValueError, match="conflict"):
        preparation.notes_decide(interpret)
    exclusion = note_request(
        report, "blocked-speech", speech="propose-exclusion", expectedSpeechRef=None
    )
    with pytest.raises(ValueError, match="protected"):
        preparation.notes_decide(exclusion)
    assert preparation.store.note_decision("blocked-interpretation") is None
    assert preparation.store.note_decision("blocked-speech") is None


def test_stage_context_rebases_by_source_and_reports_changed_evidence(tmp_path):
    _, preparation, request = prepared_note(tmp_path)
    report = preparation.notes_detect(request)
    chosen = preparation.notes_decide(
        note_request(
            report,
            "retain-motion-intent",
            interpretation="accept",
            expectedInterpretationRef=None,
        )
    )
    workspace = preparation.workspace
    assert pending_stage_notes(workspace, "sound") == []
    (original,) = pending_stage_notes(workspace, "motion")
    assert original["interpretation"]["targetId"] == "opening-title"
    assert original["decisionRef"] == chosen["decisionRef"]
    assert TimelinePipeline(workspace).authoring_context("motion")["spokenNotes"] == [
        original
    ]
    assert "spokenNotes" not in TimelinePipeline(workspace).authoring_context("sound")
    cmap = workspace.store("cmap")
    old = cmap.revision(cmap.load_index()["headRevisionId"])
    snapshot = deepcopy(old["snapshot"])
    snapshot["segments"][0]["out"]["ticks"] -= 4800
    cmap.append_revision(
        snapshot=snapshot,
        actor="creator",
        reason="Rebase the selected source occurrence",
        expected_head_hash=old["contentHash"],
    )
    assert pending_stage_notes(workspace, "motion") == [original]
    source = Path(preparation._analysis(request["analysisRef"])["sourceRef"]["locator"])
    source.write_bytes(b"Changed original source fixture")
    (stale,) = pending_stage_notes(workspace, "motion")
    assert stale["status"] == "stale"
    assert "interpretation" not in stale
