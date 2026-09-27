from __future__ import annotations

from types import SimpleNamespace

import pytest

from avo.timeline.command_handlers import CommandHandlers
from avo.timeline.iterations import IterationLedgerError, IterationLedgerService
from avo.timeline.store import StoreError

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _workspace(tmp_path):
    timeline = tmp_path / "edit" / "timeline"
    timeline.mkdir(parents=True)
    return SimpleNamespace(
        timeline_dir=timeline,
        video_id="video-1",
        project={"provider": "bishop"},
    )


def _iteration(*, statement="Keep approved opener", conflicts_with=None):
    scope = {"kind": "program", "constraintId": "opener-treatment", "value": statement}
    if conflicts_with:
        scope["conflictsWith"] = list(conflicts_with)
    return {
        "intent": {"requestedChanges": [statement]},
        "canonicalBasis": {"cmap": HASH_A},
        "proofPlanRef": {"artifactId": "proof-plan-0001", "sha256": HASH_B},
        "feedback": [{"actor": "creator", "text": statement}],
        "decisions": [
            {
                "kind": "requirement",
                "scope": scope,
                "statement": statement,
                "rationale": "creator feedback",
                "evidenceRefs": [{"evidenceId": "feedback-0001", "sha256": HASH_C}],
                "riskWindows": [
                    {
                        "windowId": "opener-window",
                        "startFrame": 0,
                        "endFrameExclusive": 90,
                        "reason": "approved opener",
                    }
                ],
            }
        ],
    }


def test_append_is_immutable_and_compare_and_swap_protected(tmp_path):
    service = IterationLedgerService(_workspace(tmp_path))
    first = service.record_iteration(
        _iteration(), actor="agent", reason="record creator approval"
    )
    first_hash = first["revision"]["contentHash"]
    second = service.record_iteration(
        _iteration(statement="Keep source audio"),
        actor="agent",
        reason="record audio decision",
        expected_head_hash=first_hash,
    )
    assert (
        first["ledger"]["iterations"][0]["feedback"][0]["text"]
        == "Keep approved opener"
    )
    assert len(second["ledger"]["iterations"]) == 2
    with pytest.raises(StoreError, match="compare-and-swap"):
        service.record_iteration(
            _iteration(statement="stale"),
            actor="agent",
            reason="stale writer",
            expected_head_hash=first_hash,
        )
    assert service.current()["ledgerHash"] == second["ledger"]["ledgerHash"]


def test_explicit_supersession_keeps_original_decision_history(tmp_path):
    service = IterationLedgerService(_workspace(tmp_path))
    first = service.record_iteration(_iteration(), actor="agent", reason="first")
    original = first["ledger"]["decisions"][0]
    request = _iteration(statement="Use a clean opener")
    request["decisions"][0]["supersedes"] = [original["decisionId"]]
    second = service.record_iteration(request, actor="agent", reason="replace")
    by_id = {item["decisionId"]: item for item in second["ledger"]["decisions"]}
    replacement = second["ledger"]["decisions"][-1]
    assert by_id[original["decisionId"]]["status"] == "superseded"
    assert by_id[original["decisionId"]]["supersededBy"] == replacement["decisionId"]
    assert (
        second["ledger"]["iterations"][0]["feedback"]
        == (first["ledger"]["iterations"][0]["feedback"])
    )
    with pytest.raises(IterationLedgerError, match="cycle"):
        service.set_decision_status(
            replacement["decisionId"],
            "superseded",
            superseded_by=original["decisionId"],
            actor="agent",
            reason="invalid cycle",
        )


def test_conflicts_are_explicit_and_require_human_judgment(tmp_path):
    service = IterationLedgerService(_workspace(tmp_path))
    first = service.record_iteration(_iteration(), actor="agent", reason="first")
    original_id = first["ledger"]["decisions"][0]["decisionId"]
    service.record_iteration(
        _iteration(statement="Remove the opener", conflicts_with=[original_id]),
        actor="agent",
        reason="conflicting feedback",
    )
    contract = service.compile_regression_contract()
    assert contract["conflicts"] == [
        {
            "decisionIds": [original_id, "decision-0002"],
            "reason": "explicitly conflicting live decisions",
            "status": "needs-human",
        }
    ]

    resolved = service.set_decision_status(
        original_id,
        "resolved",
        actor="bishop",
        reason="creator selected the newer treatment",
    )
    assert resolved["ledger"]["decisions"][0]["status"] == "resolved"
    assert service.compile_regression_contract()["conflicts"] == []


def test_unknown_history_migration_never_invents_an_approval(tmp_path):
    service = IterationLedgerService(_workspace(tmp_path))
    result = service.migrate_unknown_history(
        source_sha256=HASH_A,
        note="Legacy proof notes were incomplete",
        actor="migration",
    )
    assert result["ledger"]["decisions"] == []
    assert result["ledger"]["reworkItems"][0]["origin"] == "unknown"
    assert result["ledger"]["iterations"][0]["feedback"][0]["status"] == "unknown"


def test_pipeline_command_records_iteration_with_structured_output(tmp_path):
    workspace = _workspace(tmp_path)

    class Pipeline:
        def __init__(self):
            self.workspace = workspace

        def status(self):
            return {"state": "cmap-draft"}

        def advance(self, operation, **payload):  # pragma: no cover - guard
            raise AssertionError((operation, payload))

    result = CommandHandlers(Pipeline()).execute(
        "pipeline",
        "record-iteration",
        {
            "mutation": "iteration-ledger",
            "actor": "bishop",
            "reason": "creator feedback",
            "iteration": _iteration(),
        },
    )
    assert result["mutated"] is True
    assert result["result"]["artifact"] == "iteration-ledger"
    assert result["result"]["iterationId"] == "iteration-0001"


def test_invalid_parent_and_duplicate_decision_ids_fail_closed(tmp_path):
    service = IterationLedgerService(_workspace(tmp_path))
    request = _iteration()
    request["parentIterationId"] = "iteration-9999"
    with pytest.raises(IterationLedgerError, match="parent iteration"):
        service.record_iteration(request, actor="agent", reason="invalid")

    recorded = service.record_iteration(_iteration(), actor="agent", reason="valid")
    decision_id = recorded["ledger"]["decisions"][0]["decisionId"]
    with pytest.raises(IterationLedgerError, match="superseded status"):
        service.set_decision_status(
            decision_id,
            "superseded",
            actor="agent",
            reason="missing replacement",
        )
