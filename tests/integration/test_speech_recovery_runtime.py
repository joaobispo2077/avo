"""Explicit local ASR qualification; no download or ordinary-CI model prerequisite."""

import json
import os
import shutil
import wave
from pathlib import Path

import pytest
from tests import cutting_fixtures

from avo.adapters.registry import build_preparation_service
from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.cutting_policy import resolve_cutting_policy
from avo.timeline.cutting_service import CuttingService

PIN = os.environ.get("AVO_TEST_SPEECH_RECOVERY_PIN")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not PIN, reason="explicit prepared AVO_TEST_SPEECH_RECOVERY_PIN required"
    ),
]


def test_real_local_asr_retains_source_offset_alternatives_and_reuses_restart(
    tmp_path, monkeypatch, record_property
):
    with Path(PIN).open("rb") as stream:
        data = stream.read(65537)
    assert len(data) <= 65536
    pin = json.loads(data)
    original = Path(pin["sourcePath"])
    assert file_fingerprint(original)["sha256"] == pin["sourceSha256"]

    def source(path):
        shutil.copyfile(original, path)
        return path

    monkeypatch.setattr(cutting_fixtures, "write_dialogue_wav", source)
    workspace, media = cutting_fixtures.cutting_workspace(tmp_path)
    with wave.open(str(media), "rb") as audio:
        assert audio.getframerate() == 48000 and audio.getnchannels() == 1
        frames = audio.getnframes()
    snapshot = cutting_fixtures.source_snapshot(media)
    snapshot["segments"][0]["out"]["ticks"] = frames
    CMapService(workspace).author(
        snapshot, actor="qualification", reason="explicit synthetic source"
    )
    workspace.project["models"] = {"transcribe": pin["model"]}
    if pin.get("alignment"):
        workspace.project["cutting"] = {"runtimeRefs": {"alignment": pin["alignment"]}}
    workspace.project_path.write_text(json.dumps(workspace.project), encoding="utf-8")
    cutting = CuttingService(
        workspace,
        policy=resolve_cutting_policy(
            project_settings={"enabled": True, "family": "analysis-review"}
        ),
    )
    original_ref = cutting.analyze()["coverage"]["speech"][0]["analysisRef"]
    original_analysis = cutting.store.load_document(original_ref)
    service = build_preparation_service(workspace, recover=True)
    actual_recover = service.recovery_port.recover

    def recorded(*args, **kwargs):
        result = actual_recover(*args, **kwargs)
        (tmp_path / "actual-recovery-output.json").write_text(
            json.dumps(result), encoding="utf-8"
        )
        return result

    monkeypatch.setattr(service.recovery_port, "recover", recorded)
    end = min(frames, 48000 * 15)
    request = {
        "contractVersion": "1.0.0",
        "operation": "recover",
        "operationId": "actual-local-asr",
        "actor": "qualification",
        "reason": "selected source-clock recovery check",
        "analysisRef": original_ref,
        "selection": resolve_editing_craft_selection(
            invocation={"speechRecovery": {"enabled": True}}
        ),
        "language": pin.get("language", "en"),
        "ranges": [
            {
                "sourceId": "dialogue",
                "startTicks": 12000,
                "endTicksExclusive": end,
                "timebase": {"num": 1, "den": 48000},
            }
        ],
    }
    head = workspace.store("cmap").head_hash()
    shown = service.recover(request)
    assert shown["status"] == "pending-review", shown
    (row,) = shown["results"]
    result = service.store.load_document(row["resultRef"])["payload"]
    transcript = result["recovered"]["transcript"]
    assert transcript["words"] and transcript["sourceStart"] == 0.25
    assert all(
        0.25 <= word["start"] <= word["end"] <= end / 48000
        for word in transcript["words"]
    )
    assert (
        transcript["analysisProvenance"]["sourceFingerprint"]
        == file_fingerprint(media)["sha256"]
    )
    assert result["selection"] == "pending"
    analysis = result["recovered"]["analysis"]
    if pin.get("alignment"):
        assert analysis["alignment"]["status"] == "pass", analysis["uncertainty"]
        assert analysis["alignment"]["characters"]
        assert any(word.get("eligibleEdge") is True for word in analysis["words"])
        assert all(
            0.25 <= word["start"] < word["end"] <= end / 48000
            for word in analysis["words"]
            if word.get("eligibleEdge") is True
        )
        assert result["wordAnchorsEligible"] == service._word_eligibility(analysis)
    else:
        assert result["wordAnchorsEligible"] is False
    assert result["recovered"]["analysis"]["coverage"]["observed"] is True
    assert service.store.load_document(original_ref) == original_analysis
    resumed = build_preparation_service(workspace, recover=True)
    monkeypatch.setattr(
        resumed.recovery_port,
        "recover",
        lambda *a, **k: pytest.fail("identical restart repeated model inference"),
    )
    again = resumed.recover(request)
    assert again["results"][0]["resultRef"] == row["resultRef"]
    choice = {
        "contractVersion": "1.0.0",
        "operation": "recover-decide",
        "operationId": "actual-local-asr-choice",
        "actor": "qualification",
        "reason": "retain real ASR text with uncertain timing",
        "requestRef": shown["requestRef"],
        "resultRef": row["resultRef"],
        "intervalIndex": 0,
        "choice": "recovered",
        "expectedLedgerHash": resumed.store.head_hash(),
        "expectedDecisionRefs": [],
    }
    selected = resumed.decide(choice)
    context = resumed._source_context(request)
    evidence = resumed.source_evidence(
        context["source"],
        source_range=context["binding"]["sourceRange"],
        routing=context["routing"],
        sync_ref=context["syncRef"],
    )
    assert evidence["status"] == "selected", evidence["issues"]
    assert selected["decisionRef"] in evidence["decisionRefs"]
    if not result["wordAnchorsEligible"]:
        assert evidence["protectedRanges"]
    assert selected["wordAnchorsEligible"] == result["wordAnchorsEligible"]
    assert selected["cutApproval"] == "not-granted"
    assert service.store.load_document(original_ref) == original_analysis
    assert workspace.store("cmap").head_hash() == head
    assert file_fingerprint(media)["sha256"] == pin["sourceSha256"]
    frozen = service.store.load_document(shown["requestRef"])["payload"]
    record_property(
        "modelBindings", json.dumps(frozen["modelBindings"], sort_keys=True)
    )
    record_property(
        "alignmentObservation",
        json.dumps(
            {
                "status": analysis["alignment"]["status"],
                "wordCount": len(analysis["words"]),
                "eligibleWordCount": sum(
                    word.get("eligibleEdge") is True for word in analysis["words"]
                ),
                "characterCount": len(analysis["alignment"]["characters"]),
                "wordAnchorsEligible": result["wordAnchorsEligible"],
            },
            sort_keys=True,
        ),
    )
    record_property("alignmentStatus", analysis["alignment"]["status"])
    record_property(
        "eligibleWordCount",
        sum(word.get("eligibleEdge") is True for word in analysis["words"]),
    )
    record_property(
        "transcript",
        transcript["text"]
        if "text" in transcript
        else " ".join(word["text"] for word in transcript["words"]),
    )
