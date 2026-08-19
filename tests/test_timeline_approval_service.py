from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.approval_service import ApprovalService
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.review_runner import ReviewRunner
from tests.test_timeline_cmap_service import snapshot, workspace
from tests.test_timeline_review_integration import FakeQc, FakeTranscript, FakeWatch


def approved_review(tmp_path: Path):
    ws = workspace(tmp_path)
    raw = ws.raw_dir / "raw.bin"
    raw.write_bytes(b"raw")
    revision = CMapService(ws).author(snapshot(raw), actor="agent", reason="cut")
    candidate = ws.raw_dir / "edit" / "proof.mp4"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"proof")
    candidate_hash = file_fingerprint(candidate)["sha256"]
    dependencies = {
        "cmap": revision["contentHash"],
        "sync-map": revision["snapshot"]["syncRef"]["contentSha256"],
        "cutOutput": candidate_hash,
    }
    review = ReviewRunner(
        review_root=ws.review_dir,
        transcription=FakeTranscript(),
        watch=FakeWatch(),
        deterministic_qc=FakeQc(),
        workspace=ws,
        clock=lambda: "2026-08-13T00:00:00Z",
    ).run(
        checkpoint="cut-proof",
        candidate=candidate,
        dependencies=dependencies,
        render_profile="proof",
        risk_windows=[{"start": 0, "end": 1, "reason": "join"}],
    )
    materialization = {
        "schemaVersion": "1.0.0",
        "kind": "cut-proof",
        "materializationId": "cut-proof-test",
        "cmapRevisionId": revision["revisionId"],
        "canonicalInputLock": {
            "cmapRevisionId": revision["revisionId"],
            "cmapRevisionHash": revision["contentHash"],
            "syncRevisionId": revision["snapshot"]["syncRef"]["revisionId"],
            "syncRevisionHash": revision["snapshot"]["syncRef"]["contentSha256"],
            "rawFingerprints": {"camera": file_fingerprint(raw)["sha256"]},
        },
        "renderProfile": "proof",
        "projectionHash": "9" * 64,
        "output": {
            "path": str(candidate),
            "sha256": candidate_hash,
            "sizeBytes": candidate.stat().st_size,
        },
        "producer": {"name": "fixture", "version": "1"},
        "createdAt": "2026-08-13T00:00:00Z",
    }
    materialization["materializationHash"] = content_hash(materialization)
    path = ws.timeline_dir / "materializations" / "cut-proof" / "fixture.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(materialization), encoding="utf-8")
    return ws, revision, review, path


def test_exact_ai_passed_review_records_effective_cmap_approval(tmp_path: Path) -> None:
    ws, revision, review, materialization_path = approved_review(tmp_path)
    event = ApprovalService(ws).decide(
        decision="approved",
        revision_id=revision["revisionId"],
        review_path=review["reviewPath"],
        materialization_path=materialization_path,
        actor="creator",
        reason="approved exact cut",
    )
    assert event["candidateSha256"] == review["candidate"]["sha256"]
    assert ws.store("cmap").effective_approval()["eventId"] == event["eventId"]


def test_changed_candidate_or_stale_review_cannot_approve(tmp_path: Path) -> None:
    ws, revision, review, materialization_path = approved_review(tmp_path)
    materialization = json.loads(materialization_path.read_text(encoding="utf-8"))
    materialization["output"]["sha256"] = "0" * 64
    materialization_path.write_text(json.dumps(materialization), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate"):
        ApprovalService(ws).decide(
            decision="approved",
            revision_id=revision["revisionId"],
            review_path=review["reviewPath"],
            materialization_path=materialization_path,
            actor="creator",
            reason="must fail",
        )


def test_decide_updates_editlog_approvals(tmp_path: Path) -> None:
    ws, revision, review, materialization_path = approved_review(tmp_path)
    event = ApprovalService(ws).decide(
        decision="approved",
        revision_id=revision["revisionId"],
        review_path=review["reviewPath"],
        materialization_path=materialization_path,
        actor="creator",
        reason="approved exact cut",
    )
    assert event["editlogRefresh"]["ok"] is True
    text = (ws.raw_dir / "EDITLOG.md").read_text(encoding="utf-8")
    assert "## Approvals" in text
    assert "approved exact cut" in text
    assert "Approvals: none recorded yet" not in text
