from __future__ import annotations

import json

import pytest

from avo.learndown_export import (
    build_timeline_learning_snapshot,
    export_timeline_learning_snapshot,
    load_active_timeline_learning,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _ledger():
    return {
        "videoId": "video-1",
        "provider": "bishop",
        "ledgerHash": SHA_A,
        "iterations": [{"iterationId": "iteration-0001"}],
        "decisions": [
            {
                "decisionId": "decision-0001",
                "statement": "Never use C:\\private\\footage.mp4 as a proof source",
                "status": "active",
                "scope": {"kind": "lineage"},
                "evidenceRefs": [{"kind": "approval"}],
            }
        ],
        "reworkItems": [
            {
                "reworkId": "rework-0001",
                "reworkGroupId": "group-0001",
                "origin": "user-scope-change",
                "summary": "A new clip arrived after approval",
                "evidenceRefs": [{"kind": "feedback"}],
                "impact": {"renderCost": 2, "reviewCost": 1},
                "supersedes": None,
                "capabilityGap": None,
            },
            {
                "reworkId": "rework-0002",
                "reworkGroupId": "group-0002",
                "origin": "avo-capability-gap",
                "summary": "Needed reusable event synchronization",
                "evidenceRefs": [{"kind": "regression"}],
                "impact": {"renderCost": 3, "reviewCost": 4},
                "supersedes": None,
                "capabilityGap": {
                    "operation": "event-sync",
                    "desiredBehavior": "Bind visual impact and transient once",
                },
            },
        ],
    }


def test_snapshot_separates_scope_from_capability_and_sanitizes_paths() -> None:
    snapshot = build_timeline_learning_snapshot(
        ledger=_ledger(),
        candidate_snapshot_hash=SHA_B,
        status="draft",
        prevention_rules=[
            {
                "id": "rule-0001",
                "summary": "Reject prior proofs during preflight",
                "status": "verified",
                "recurrence": 3,
            }
        ],
        created_at="2026-09-27T00:00:00Z",
    )
    encoded = json.dumps(snapshot)
    assert "C:\\\\private" not in encoded
    assert "[project-path]" in encoded
    assert snapshot["reworkGroups"][0]["impact"]["origins"] == ["user-scope-change"]
    assert snapshot["capabilityGaps"][0]["impact"]["operation"] == "event-sync"
    assert snapshot["masterFingerprint"] is None


def test_final_snapshot_requires_master_and_strips_its_locator() -> None:
    with pytest.raises(ValueError, match="approved master"):
        build_timeline_learning_snapshot(
            ledger=_ledger(), candidate_snapshot_hash=SHA_B, status="final"
        )
    snapshot = build_timeline_learning_snapshot(
        ledger=_ledger(),
        candidate_snapshot_hash=SHA_B,
        status="final",
        master_fingerprint={
            "sha256": SHA_B,
            "sizeBytes": 10,
            "locator": "C:\\private\\master.mp4",
        },
        created_at="2026-09-27T00:00:00Z",
    )
    assert snapshot["masterFingerprint"] == {"sha256": SHA_B, "sizeBytes": 10}


def test_export_is_idempotent_and_preserves_draft_when_final_activates(
    tmp_path,
) -> None:
    draft = build_timeline_learning_snapshot(
        ledger=_ledger(),
        candidate_snapshot_hash=SHA_B,
        status="draft",
        created_at="2026-09-27T00:00:00Z",
    )
    first = export_timeline_learning_snapshot(tmp_path, draft)
    assert export_timeline_learning_snapshot(tmp_path, draft) == first
    final = build_timeline_learning_snapshot(
        ledger=_ledger(),
        candidate_snapshot_hash=SHA_B,
        status="final",
        master_fingerprint={"sha256": SHA_B, "sizeBytes": 10},
        created_at="2026-09-27T00:01:00Z",
    )
    export_timeline_learning_snapshot(tmp_path, final)
    assert first.is_file()
    assert load_active_timeline_learning(tmp_path)["status"] == "final"
