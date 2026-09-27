from __future__ import annotations

from types import SimpleNamespace

from avo.timeline.contracts import content_hash, validate_document
from avo.timeline.iterations import IterationLedgerService
from avo.timeline.review import historical_review_requirements

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _service(tmp_path):
    timeline = tmp_path / "edit" / "timeline"
    timeline.mkdir(parents=True)
    workspace = SimpleNamespace(
        timeline_dir=timeline,
        video_id="video-1",
        project={"provider": "bishop"},
    )
    return IterationLedgerService(workspace)


def _request(statement, *, status="active", kind="requirement", window_id="risk-one"):
    return {
        "intent": {"requestedChanges": [statement]},
        "canonicalBasis": {"cmap": HASH_A},
        "proofPlanRef": {"artifactId": "proof-plan-0001", "sha256": HASH_B},
        "decisions": [
            {
                "kind": kind,
                "scope": {"kind": "program", "name": statement},
                "statement": statement,
                "rationale": "retained creator decision",
                "status": status,
                "evidenceRefs": [
                    {"evidenceId": f"evidence-{window_id}", "sha256": HASH_C}
                ],
                "riskWindows": [
                    {
                        "windowId": window_id,
                        "startFrame": 30,
                        "endFrameExclusive": 60,
                        "reason": statement,
                    }
                ],
            }
        ],
    }


def test_contract_uses_complete_history_and_retains_rejected_treatments(tmp_path):
    service = _service(tmp_path)
    service.record_iteration(
        _request("Keep title", window_id="title-risk"), actor="a", reason="one"
    )
    service.record_iteration(
        _request(
            "Never use blue panel",
            status="rejected",
            kind="rejection",
            window_id="panel-risk",
        ),
        actor="a",
        reason="two",
    )
    service.record_iteration(
        _request(
            "Frozen insert fixed",
            status="resolved",
            kind="defect",
            window_id="freeze-risk",
        ),
        actor="a",
        reason="three",
    )
    contract = service.compile_regression_contract()
    assert [item["statement"] for item in contract["obligations"]] == [
        "Keep title",
        "Never use blue panel",
    ]
    assert {window["windowId"] for window in contract["historicalRiskWindows"]} == {
        "title-risk",
        "panel-risk",
        "freeze-risk",
    }
    assert contract["ledgerHash"] == service.current()["ledgerHash"]
    assert contract["contractHash"] == content_hash(
        {key: value for key, value in contract.items() if key != "contractHash"}
    )
    validate_document(
        contract, "avo.iteration-ledger.schema.json#/$defs/regressionContract"
    )


def test_review_requirements_trace_windows_and_source_evidence(tmp_path):
    service = _service(tmp_path)
    service.record_iteration(
        _request("Keep crunch", window_id="crunch-risk"),
        actor="a",
        reason="one",
    )
    contract = service.compile_regression_contract()
    requirements = historical_review_requirements(service.current(), contract)
    assert requirements["ledgerHash"] == contract["ledgerHash"]
    assert requirements["contractHash"] == contract["contractHash"]
    assert requirements["requiredWindows"][0]["windowId"] == "crunch-risk"
    assert requirements["sourceEvidenceRefs"] == [
        {"evidenceId": "evidence-crunch-risk", "sha256": HASH_C}
    ]
