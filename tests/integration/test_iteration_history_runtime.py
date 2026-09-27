from __future__ import annotations

from types import SimpleNamespace

import pytest

from avo.timeline.iterations import IterationLedgerService
from avo.timeline.lifecycle import LifecycleError, PipelineRunStore

HASH_A = "a" * 64
HASH_B = "b" * 64


def test_cleaned_proof_bytes_do_not_remove_iteration_memory(tmp_path):
    timeline = tmp_path / "edit" / "timeline"
    timeline.mkdir(parents=True)
    workspace = SimpleNamespace(
        timeline_dir=timeline,
        video_id="video-1",
        project={"provider": "bishop"},
    )
    proof = tmp_path / "edit" / "preview" / "proof-v001.mp4"
    proof.parent.mkdir(parents=True)
    proof.write_bytes(b"disposable proof")
    service = IterationLedgerService(workspace)
    request = {
        "intent": {"requestedChanges": ["Keep insert synced"]},
        "canonicalBasis": {"cmap": HASH_A},
        "proofPlanRef": {"artifactId": "proof-plan-0001", "sha256": HASH_B},
        "candidate": service.fingerprint_candidate(proof),
        "feedback": [{"actor": "creator", "text": "Approved except SFX"}],
        "decisions": [
            {
                "kind": "defect",
                "scope": {"kind": "event", "eventId": "insert-one"},
                "statement": "Entry SFX must be synchronized",
                "rationale": "creator review",
                "riskWindows": [
                    {
                        "windowId": "insert-sync-risk",
                        "startFrame": 300,
                        "endFrameExclusive": 330,
                        "reason": "historical sync regression",
                    }
                ],
            }
        ],
    }
    recorded = service.record_iteration(request, actor="agent", reason="proof review")
    proof.unlink()
    cleaned = service.mark_iteration_cleaned(
        "iteration-0001",
        actor="agent",
        reason="remove bulky rejected proof",
        expected_head_hash=recorded["revision"]["contentHash"],
    )
    contract = service.compile_regression_contract()
    assert cleaned["ledger"]["iterations"][0]["candidate"]["locator"] is None
    assert (
        cleaned["ledger"]["iterations"][0]["feedback"][0]["text"]
        == "Approved except SFX"
    )
    assert contract["obligations"][0]["statement"] == "Entry SFX must be synchronized"

    run = PipelineRunStore(
        timeline / "pipeline-run.json", clock=lambda: "2026-09-27T12:00:00Z"
    )
    run.initialize(
        run_id="run-0001",
        video_id="video-1",
        provider="bishop",
        project_path=tmp_path / "avo.project.json",
    )
    bound = run.bind_iteration_context(
        ledger_revision_id=cleaned["revision"]["revisionId"],
        ledger_sha256=cleaned["revision"]["contentHash"],
        regression_contract_id=contract["contractId"],
        regression_contract_sha256=contract["contractHash"],
    )
    assert (
        bound["activeRefs"]["iterationLedger"]["sha256"]
        == (cleaned["revision"]["contentHash"])
    )
    assert (
        bound["activeRefs"]["regressionContract"]["sha256"]
        == (contract["contractHash"])
    )


def test_iteration_context_binding_is_compare_and_swap_protected(tmp_path):
    timestamps = iter(
        [
            "2026-09-27T12:00:00Z",
            "2026-09-27T12:01:00Z",
            "2026-09-27T12:02:00Z",
        ]
    )
    run = PipelineRunStore(
        tmp_path / "pipeline-run.json", clock=lambda: next(timestamps)
    )
    initial = run.initialize(
        run_id="run-0001",
        video_id="video-1",
        provider="bishop",
        project_path=tmp_path / "avo.project.json",
    )
    first = run.bind_iteration_context(
        ledger_revision_id="iteration-ledger-r0001",
        ledger_sha256=HASH_A,
        regression_contract_id="contract-iteration-0001",
        regression_contract_sha256=HASH_B,
        expected_updated_at=initial["updatedAt"],
    )
    with pytest.raises(LifecycleError, match="compare-and-swap"):
        run.bind_iteration_context(
            ledger_revision_id="iteration-ledger-r0002",
            ledger_sha256="c" * 64,
            regression_contract_id="contract-iteration-0002",
            regression_contract_sha256="d" * 64,
            expected_updated_at=initial["updatedAt"],
        )
    assert run.load()["activeRefs"] == first["activeRefs"]
