"""A consumed cross-production transfer requires an explicit reversal."""

import pytest

from avo.cost_store import CostError
from avo.costs import summarize
from test_cost_continuity import evidence, registered_ledger
from test_cost_invariants import _activity_decision, _ingest_activity
from test_costs import fact


def _transfer(store, metadata, target, operation):
    decision = _activity_decision(
        store,
        [metadata],
        relation="allocation",
        operationId=operation,
        allocations=[
            {
                "accountingVideoId": target.identity()["accountingVideoId"],
                "scope": metadata["attribution"]["scope"],
                "reference": {"kind": "evidence", "id": metadata["evidenceId"]},
            }
        ],
    )
    store.append_record("reconciliations", decision)
    return decision


def test_consumed_transfer_withdrawal_requires_exact_reverse_authority(tmp_path):
    first = registered_ledger(tmp_path / "first")
    second = registered_ledger(tmp_path / "second")
    row = fact("transfer")
    metadata = evidence(row)
    _ingest_activity(first, [row], [metadata])
    allocation = _transfer(first, metadata, second, "first-to-second")
    _ingest_activity(second, [row], [metadata])
    withdrawal = _activity_decision(
        first,
        [metadata],
        relation="withdraw",
        operationId="withdraw-transfer",
        supersedes=[allocation["reconciliationId"]],
        references=[{"kind": "decision", "id": allocation["reconciliationId"]}],
    )
    with pytest.raises(CostError, match="consumed|reverse|transfer"):
        first.append_record("reconciliations", withdrawal)
    assert summarize(first)["tokens"]["total"] is None
    assert summarize(second)["tokens"]["total"] == 120
    _transfer(second, metadata, first, "second-to-first")
    first.append_record("reconciliations", withdrawal)
    assert summarize(first)["tokens"]["total"] == 120
    assert summarize(second)["tokens"]["total"] is None


def test_explicit_transfer_chain_has_one_current_consumer(tmp_path):
    first, second, third = (
        registered_ledger(tmp_path / name) for name in ("first", "second", "third")
    )
    row = fact("transfer-chain")
    metadata = evidence(row)
    _ingest_activity(first, [row], [metadata])
    _transfer(first, metadata, second, "chain-first-second")
    _ingest_activity(second, [row], [metadata])
    _transfer(second, metadata, third, "chain-second-third")
    _ingest_activity(third, [row], [metadata])
    assert [
        summarize(store)["tokens"]["total"] for store in (first, second, third)
    ] == [None, None, 120]


@pytest.mark.parametrize("destination", ["copy", "third"])
def test_unallocated_copy_cannot_create_assignment_authority(tmp_path, destination):
    owner, copy, third = (
        registered_ledger(tmp_path / name) for name in ("owner", "copy", "third")
    )
    row = fact("reserved-native-activity")
    assigned = evidence(row)
    unallocated = evidence(
        row,
        attribution={**assigned["attribution"], "status": "unallocated"},
    )
    _ingest_activity(owner, [row], [assigned])
    _ingest_activity(copy, [row], [unallocated])
    target = copy if destination == "copy" else third
    _transfer(copy, unallocated, target, "copy-cannot-grant-authority")

    assert summarize(owner)["tokens"]["total"] == 120
    report = summarize(copy)
    assert report["tokens"]["total"] is None
    assert not report["activityEvidenceIds"]
    with pytest.raises(CostError, match="assigned|allocation|production"):
        _ingest_activity(target, [row], [assigned], operation="false-assignment")
    assert summarize(owner)["tokens"]["total"] == 120
    assert summarize(target)["tokens"]["total"] is None
