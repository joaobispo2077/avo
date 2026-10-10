"""Persistent repair budgets remain tied to original source occurrences."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from avo.timeline.cutting_store import CuttingStore, CuttingStoreError


@pytest.fixture
def store(tmp_path):
    return CuttingStore(tmp_path / "cutting", video_id="video", provider="bishop")


def reserve(store, *, expected=None, occurrence="source-unit-1", selection="a" * 64):
    return store.reserve_repair(
        occurrence_id=occurrence,
        proposal_ref={"locator": "proposal.json", "sha256": "b" * 64},
        selection_hash=selection,
        actor="agent",
        expected_head_hash=expected,
    )


def test_initial_compare_and_swap_is_not_optional(store):
    reserve(store)
    with pytest.raises(CuttingStoreError, match="compare-and-swap"):
        reserve(store)


def test_crashed_and_failed_reservations_are_consumed_across_resume(store):
    first = reserve(store)
    reopened = CuttingStore(store.directory, video_id="video", provider="bishop")
    second = reserve(reopened, expected=reopened.head_hash(), selection="c" * 64)
    assert [first["payload"]["ordinal"], second["payload"]["ordinal"]] == [1, 2]
    with pytest.raises(CuttingStoreError, match="two"):
        reserve(reopened, expected=reopened.head_hash(), selection="d" * 64)


def test_other_source_occurrence_has_independent_budget(store):
    reserve(store)
    second = reserve(store, expected=store.head_hash(), occurrence="source-unit-2")
    assert second["payload"]["ordinal"] == 1


def binding(start, end, anchor="unit-a", source="a" * 64):
    return {
        "sourceSha256": source,
        "unitAnchor": anchor,
        "sourceRange": {
            "sourceId": "source-1",
            "startTicks": start,
            "endTicksExclusive": end,
            "timebase": {"num": 1, "den": 1000},
        },
    }


def reserve_bound(store, identity, original):
    return store.reserve_repair(
        occurrence_id=identity,
        original_binding=original,
        proposal_ref={"locator": "proposal.json", "sha256": "b" * 64},
        selection_hash="a" * 64,
        actor="agent",
        expected_head_hash=store.head_hash(),
    )


def test_refined_boundary_and_changed_identity_cannot_reset_budget(store):
    first = reserve_bound(store, "original", binding(100, 300))
    second = reserve_bound(store, "refined", binding(150, 350, anchor="unit-renamed"))
    assert second["payload"]["ordinal"] == 2
    assert second["payload"]["budgetOccurrenceId"] == first["payload"]["occurrenceId"]
    with pytest.raises(CuttingStoreError, match="two automatic"):
        reserve_bound(
            store, "another-refinement", binding(310, 400, anchor="third-name")
        )


def test_lexical_anchor_survives_nonoverlapping_boundary_reestimate(store):
    reserve_bound(store, "original", binding(100, 300))
    assert reserve_bound(store, "moved", binding(400, 500))["payload"]["ordinal"] == 2
    with pytest.raises(CuttingStoreError, match="two automatic"):
        reserve_bound(store, "moved-again", binding(600, 700))


def test_distinct_nonoverlapping_original_units_have_independent_budget(store):
    reserve_bound(store, "unit-one", binding(100, 300))
    assert (
        reserve_bound(store, "unit-two", binding(400, 500, anchor="unit-b"))["payload"][
            "ordinal"
        ]
        == 1
    )
    assert (
        reserve_bound(store, "other-source", binding(100, 300, source="c" * 64))[
            "payload"
        ]["ordinal"]
        == 1
    )


def test_duplicate_transport_retry_does_not_reserve_again(store):
    first = reserve(store)
    assert store.reservations("source-unit-1") == [first]
    assert store.reservations("source-unit-2") == []


def test_concurrent_initial_reservations_have_one_winner(store):
    def claim(_):
        try:
            return reserve(store)
        except CuttingStoreError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(store.reservations("source-unit-1")) == 1


def test_document_bodies_are_immutable_and_tampering_rejected(store):
    document = reserve(store)
    ref = store.save_document(document)
    assert store.load_document(ref) == document
    path = store.directory / ref["locator"]
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(CuttingStoreError):
        store.load_document(ref)


def test_failed_result_does_not_refund_or_mutate_reservation(store):
    first = reserve(store)
    result = store.record_result(
        first,
        status="failed",
        result_ref={"locator": "verification.json", "sha256": "e" * 64},
        actor="agent",
        expected_head_hash=store.head_hash(),
    )
    assert result["payload"]["status"] == "failed"
    assert store.reservations("source-unit-1") == [first]
    assert reserve(store, expected=store.head_hash())["payload"]["ordinal"] == 2
    with pytest.raises(CuttingStoreError, match="terminal outcome"):
        store.record_result(
            first,
            status="completed",
            result_ref=first["payload"]["proposalRef"],
            actor="agent",
            expected_head_hash=store.head_hash(),
        )


def test_reference_cannot_escape_store(store):
    with pytest.raises(CuttingStoreError, match="escapes"):
        store.load_document({"locator": "../outside.json", "sha256": "a" * 64})


def test_processes_cannot_both_claim_initial_head(store):
    script = (
        "from pathlib import Path; from avo.timeline.cutting_store import CuttingStore; "
        "import sys; s=CuttingStore(Path(sys.argv[1]),video_id='video',provider='bishop'); "
        "s.reserve_repair(occurrence_id='source-unit-1',"
        "proposal_ref={'locator':'proposal.json','sha256':'b'*64},selection_hash='a'*64,"
        "actor='agent',expected_head_hash=None)"
    )

    def claim(_):
        return subprocess.run(
            [sys.executable, "-c", script, str(store.directory)],
            capture_output=True,
            timeout=30,
            check=False,
        ).returncode

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert results.count(0) == 1
    assert len(store.reservations("source-unit-1")) == 1
