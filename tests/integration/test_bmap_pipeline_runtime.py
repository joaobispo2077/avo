from __future__ import annotations

import json
from pathlib import Path

from avo.timeline.approval_service import ApprovalService
from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.review_runner import ReviewRunner

from tests.test_timeline_bmap_service import approved_workspace, cue
from tests.test_timeline_cmap_service import snapshot
from tests.test_timeline_review_integration import FakeQc, FakeTranscript, FakeWatch


def approve_current_cmap(workspace, revision, ordinal: int):
    candidate = workspace.raw_dir / "edit" / f"proof-{ordinal}.mp4"
    candidate.write_bytes(f"proof-{ordinal}".encode())
    candidate_hash = file_fingerprint(candidate)["sha256"]
    dependencies = {
        "cmap": revision["contentHash"],
        "sync-map": revision["snapshot"]["syncRef"]["contentSha256"],
        "cutOutput": candidate_hash,
    }
    review = ReviewRunner(
        review_root=workspace.review_dir,
        transcription=FakeTranscript(),
        watch=FakeWatch(),
        deterministic_qc=FakeQc(),
        workspace=workspace,
        clock=lambda: "2026-08-13T00:00:00Z",
    ).run(
        checkpoint="cut-proof",
        candidate=candidate,
        dependencies=dependencies,
        render_profile="proof",
        risk_windows=[{"start": 0, "end": 0.5, "reason": "join"}],
    )
    materialization = {
        "schemaVersion": "1.0.0",
        "kind": "cut-proof",
        "materializationId": f"proof-{ordinal}",
        "cmapRevisionId": revision["revisionId"],
        "canonicalInputLock": {
            "cmapRevisionId": revision["revisionId"],
            "cmapRevisionHash": revision["contentHash"],
            "syncRevisionId": revision["snapshot"]["syncRef"]["revisionId"],
            "syncRevisionHash": revision["snapshot"]["syncRef"]["contentSha256"],
            "rawFingerprints": {
                item["sourceId"]: item["fingerprint"]["sha256"]
                for item in revision["snapshot"]["sources"]
            },
        },
        "renderProfile": "proof",
        "projectionHash": "8" * 64,
        "output": {
            "path": str(candidate),
            "sha256": candidate_hash,
            "sizeBytes": candidate.stat().st_size,
        },
        "producer": {"name": "fixture", "version": "1"},
        "createdAt": "2026-08-13T00:00:00Z",
    }
    materialization["materializationHash"] = content_hash(materialization)
    path = workspace.timeline_dir / "materializations" / "cut-proof" / f"proof-{ordinal}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(materialization), encoding="utf-8")
    ApprovalService(workspace).decide(
        decision="approved",
        revision_id=revision["revisionId"],
        review_path=review["reviewPath"],
        materialization_path=path,
        actor="creator",
        reason=f"approve cut {ordinal}",
    )


def test_bmap_revision_stale_rebase_and_human_blocker_lifecycle(tmp_path: Path) -> None:
    workspace, _, _ = approved_workspace(tmp_path)
    beat = cue()
    beat["rawAnchorRanges"] = [[100, 400]]
    first_bmap = BMapService(workspace).author(
        {"cues": [beat]},
        actor="avo",
        reason="initial beat",
    )
    raw = workspace.raw_dir / "raw.bin"
    second_cmap = CMapService(workspace).author(
        snapshot(raw, start=50, end=950),
        actor="avo",
        reason="new approved cut",
    )
    assert workspace.store("bmap").load_index()["activeState"] == "stale"
    approve_current_cmap(workspace, second_cmap, 2)

    result = BMapService(workspace).rebase(
        {"cue-one": [[150, 450]]},
        actor="avo",
        reason="unique shift",
    )
    assert result["revision"] is not None
    assert result["outcomes"][0]["outcome"] == "shifted"
    assert workspace.store("bmap").load_index()["activeState"] == "valid"

    third_cmap = CMapService(workspace).author(
        snapshot(raw, start=100, end=900),
        actor="avo",
        reason="another cut",
    )
    approve_current_cmap(workspace, third_cmap, 3)
    blocked = BMapService(workspace).rebase(
        {"cue-one": [[150, 450], [500, 800]]},
        actor="avo",
        reason="ambiguous mapping",
    )
    assert blocked["revision"] is None
    assert blocked["blockers"][0]["outcome"] == "ambiguous"
    assert Path(blocked["reportPath"]).is_file()
