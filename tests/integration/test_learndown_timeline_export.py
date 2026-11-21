from __future__ import annotations

import json

import pytest
from tests.test_iteration_ledger import _iteration

from avo.learndown_export import (
    build_timeline_learning_snapshot,
    export_provider_learndown,
    export_timeline_learning_snapshot,
    load_active_timeline_learning,
)
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.workspace import TimelineWorkspace


def test_exact_lineage_snapshot_is_loadable_without_old_proof_media(tmp_path) -> None:
    sha = "a" * 64
    ledger = {
        "videoId": "video-1",
        "provider": "bishop",
        "ledgerHash": sha,
        "iterations": [{"iterationId": "iteration-0001"}],
        "decisions": [],
        "reworkItems": [],
    }
    snapshot = build_timeline_learning_snapshot(
        ledger=ledger,
        candidate_snapshot_hash="b" * 64,
        reconstruction_bundle_hash="c" * 64,
        status="final",
        master_fingerprint={"sha256": "d" * 64, "sizeBytes": 123},
        prevention_rules=[
            {
                "id": "rule-0001",
                "summary": "Build every proof from canonical sources",
                "status": "verified",
            }
        ],
        created_at="2026-09-27T00:00:00Z",
    )
    export_timeline_learning_snapshot(tmp_path, snapshot)
    loaded = load_active_timeline_learning(tmp_path)
    assert loaded["iterationLedgerHash"] == sha
    assert loaded["reconstructionBundleHash"] == "c" * 64
    assert loaded["preventionRules"][0]["summary"].startswith("Build every proof")


def test_final_learning_loads_for_new_project_without_inheriting_approval(
    tmp_path,
) -> None:
    learning_root = tmp_path / "provider-learning"
    entry = learning_root / "prior-video"
    snapshot = build_timeline_learning_snapshot(
        ledger={
            "videoId": "prior-video",
            "provider": "bishop",
            "ledgerHash": "a" * 64,
            "iterations": [],
            "decisions": [],
            "reworkItems": [],
        },
        candidate_snapshot_hash="b" * 64,
        reconstruction_bundle_hash="c" * 64,
        status="final",
        master_fingerprint={"sha256": "d" * 64, "sizeBytes": 123},
        prevention_rules=[
            {"id": "source-only", "summary": "Build from sources", "status": "verified"}
        ],
        created_at="2026-09-27T00:00:00Z",
    )
    export_timeline_learning_snapshot(entry, snapshot)
    raw_dir = tmp_path / "new-video"
    raw_dir.mkdir()
    workspace = TimelineWorkspace(
        project_path=raw_dir / "avo.project.json",
        project={
            "provider": "bishop",
            "providerLearningDirectory": str(learning_root),
        },
        raw_dir=raw_dir,
        video_id="new-video",
    )

    loaded = workspace.finalized_provider_learning()
    assert [item["snapshotId"] for item in loaded] == [snapshot["snapshotId"]]

    compiler = ProofPlanCompiler(workspace)
    compiler.workspace.finalized_provider_learning = lambda: loaded
    plan = {
        "proofPlanId": "proof-plan-test",
        "proofPlanHash": "invalid-for-this-unit-boundary",
        "canonicalInputLock": {},
        "output": {"path": str(raw_dir / "proof.mp4")},
        "implementationRefs": [],
        "capabilityResolution": [],
        "lineagePolicy": {"prohibitedMediaClasses": []},
    }
    report = compiler.preflight(plan, media_inputs={}, tool_readiness={})
    guidance = report["providerLearning"]
    assert guidance["binding"] is False
    assert guidance["inheritedApprovals"] is False
    assert guidance["snapshots"][0]["preventionRules"][0]["id"] == "source-only"


@pytest.mark.parametrize("matches_approval", [True, False])
def test_wrap_export_publishes_learning_only_for_approved_current_master(
    tmp_path, monkeypatch, matches_approval
):
    from avo.timeline.delivery import DeliveryService
    from avo.timeline.iterations import IterationLedgerService

    raw = tmp_path / "raw"
    raw.mkdir()
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps({"provider": "bishop", "videoId": "approved-video"}),
        encoding="utf-8",
    )
    workspace = TimelineWorkspace.from_project(project)
    result = IterationLedgerService(workspace).record_iteration(
        _iteration(), actor="agent", reason="record current review"
    )
    delivery = DeliveryService(workspace)
    delivery.manifest_path.parent.mkdir(exist_ok=True)
    manifest = {
        "state": "delivered",
        "master": {
            "path": str(raw / "master-v001.mp4"),
            "sha256": "a" * 64,
            "sizeBytes": 42,
        },
        "candidateSnapshot": {"sha256": "b" * 64},
        "dependencyLockSha256": "c" * 64,
        "review": {"candidateIdentityHash": "d" * 64},
        "approval": {
            "decision": "approved",
            "checkpoint": "deliver",
            "candidateIdentityHash": "d" * 64,
            "candidateSha256": ("a" if matches_approval else "f") * 64,
            "dependencyLockSha256": "c" * 64,
        },
    }
    delivery.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(DeliveryService, "validate_current", lambda _self: manifest)
    payload = {
        "provider": "bishop",
        "rawDir": str(raw),
        "masterBasename": "master-v001",
        "status": "final",
        "generatedAt": "2026-11-19T00:00:00Z",
    }

    entry = export_provider_learndown(payload, root=tmp_path)
    assert entry is not None
    learning = load_active_timeline_learning(entry)
    if matches_approval:
        assert learning["masterFingerprint"] == {"sha256": "a" * 64, "sizeBytes": 42}
        assert learning["candidateSnapshotHash"] == "b" * 64
        assert learning["iterationLedgerHash"] == result["ledger"]["ledgerHash"]
        assert learning["decisionOutcomes"][0]["learningScope"] == "project-only"
        assert export_provider_learndown(payload, root=tmp_path) == entry
    else:
        assert learning is None
