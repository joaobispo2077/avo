from types import SimpleNamespace

import pytest

from avo.timeline.iterations import IterationLedgerError, IterationLedgerService


def test_iteration_retains_exact_cutting_refs_without_new_approval(tmp_path):
    workspace = SimpleNamespace(
        timeline_dir=tmp_path, video_id="fixture", project={"provider": "bishop"}
    )
    service = IterationLedgerService(workspace)
    ref = {"locator": "documents/proposal/example.json", "sha256": "a" * 64}
    result = service.record_iteration(
        {
            "intent": {"requestedChanges": ["cutting proposal"]},
            "canonicalBasis": {"cmap": "b" * 64},
            "proofPlanRef": {"artifactId": "planned", "sha256": "c" * 64},
            "cuttingRefs": {"proposal": ref},
        },
        actor="fixture",
        reason="bind evidence",
    )
    iteration = result["ledger"]["iterations"][0]
    assert iteration["intent"]["cutting"]["proposal"] == ref
    assert iteration["findings"][0]["sha256"] == ref["sha256"]
    assert result["ledger"]["decisions"] == []


def test_invalid_cutting_ref_cannot_enter_iteration(tmp_path):
    workspace = SimpleNamespace(
        timeline_dir=tmp_path, video_id="fixture", project={"provider": "bishop"}
    )
    service = IterationLedgerService(workspace)
    with pytest.raises(IterationLedgerError, match="cutting"):
        service.record_iteration(
            {"cuttingRefs": {"proposal": {"locator": "a", "sha256": "bad"}}},
            actor="fixture",
            reason="invalid",
        )
