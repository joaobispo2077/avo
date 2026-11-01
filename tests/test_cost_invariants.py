"""Regression proof for review-discovered counting and persistence risks."""

import json

import pytest

from avo.cost_sources import collect
from avo.cost_store import CostError, CostStore
from avo.costs import summarize
from test_cost_continuity import (
    FIXED_TIME,
    PARTICIPATION_ID,
    evidence,
    observation_key,
    packet,
    participation_fact,
    profile,
    receipt,
    registered_ledger,
)
from test_costs import fact


@pytest.fixture(autouse=True)
def isolated_cost_registry(tmp_path, monkeypatch):
    from avo import avo_state

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")


def ledger(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    return store


def test_three_consecutive_video_bindings(tmp_path, monkeypatch):
    from avo import avo_state

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    source = tmp_path / "usage.json"
    source.write_text(json.dumps([fact("a"), fact("b"), fact("c")]))
    for index, (start, end) in enumerate([("beginning", "a"), ("a", "b"), ("b", "c")]):
        store = ledger(tmp_path / str(index))
        binding = store.bind(
            source=source, agent="codex", session_id="session", boundary=start
        )
        store.close_binding(binding["bindingId"], end)
        collect(store)
        assert summarize(store)["observationCount"] == 1


def test_incomplete_rates_and_unknown_overlap_cannot_underprice():
    from avo.costs import _priced_buckets

    assert _priced_buckets(fact(), {"rates": {"input": "1"}}) is None
    row = fact(semantics={"cacheRead": "unknown", "reasoning": "output"})
    assert (
        _priced_buckets(
            row, {"rates": {"input": "1", "output": "2", "cacheRead": "0.1"}}
        )
        is None
    )


def test_missing_additive_category_is_not_zero():
    from avo.costs import _priced_buckets, _token_total

    row = fact(
        tokens={"input": 100, "output": 20, "cacheRead": None},
        semantics={"cacheRead": "disjoint"},
    )
    assert _token_total(row) is None
    row["semantics"]["cacheRead"] = "unknown"
    assert _token_total(row) is None
    assert _priced_buckets(row, {"rates": {"input": "1", "output": "2"}}) is None


def test_path_check_does_not_re_resolve_creating_directories(tmp_path, monkeypatch):
    from pathlib import Path

    store = ledger(tmp_path)
    original = Path.resolve

    def transient_resolve(path, *args, **kwargs):
        if path == store.root:
            return path.parent / "transient-windows-resolution"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", transient_resolve)
    assert store.path("identity.json") == store.root / "identity.json"


def test_path_check_rejects_windows_reparse_directory(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    import pytest

    from avo.cost_store import CostError

    store = ledger(tmp_path)
    original = Path.lstat

    def reparse_stat(path, *args, **kwargs):
        if path == store.root:
            return SimpleNamespace(st_mode=0o40755, st_file_attributes=0x400)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", reparse_stat)
    with pytest.raises(CostError, match="link"):
        store.path("identity.json")


def test_required_pricing_dimensions_must_match(tmp_path):
    store = ledger(tmp_path)
    price = {
        "schemaVersion": "1.0.0",
        "model": "model-a",
        "serviceProvider": "service-a",
        "unit": "USD",
        "basis": "calculated-estimate",
        "provenance": "fixture",
        "effectiveAt": "2026-10-22T00:00:00Z",
        "denominator": 1000,
        "rates": {"input": "1", "output": "2"},
        "dimensions": {"tier": "priority"},
    }
    store.price(price)
    store.ingest(
        [
            fact("missing", amounts=[]),
            fact("known", amounts=[], pricingDimensions={"tier": "priority"}),
        ]
    )
    report = summarize(store)
    assert report["amounts"][0]["amount"] == "0.14"
    assert report["coverage"] == "partial"


def test_closed_binding_does_not_absorb_later_video_work(tmp_path):
    store = ledger(tmp_path)
    source = tmp_path / "source.json"
    source.write_text(json.dumps([fact("a"), fact("b")]))
    binding = store.bind(
        source=source, agent="codex", session_id="session", boundary="beginning"
    )
    store.close_binding(binding["bindingId"], "b")
    source.write_text(json.dumps([fact("a"), fact("b"), fact("another-video")]))
    collect(store)
    assert summarize(store)["observationCount"] == 2


def test_partial_child_cannot_replace_rollup(tmp_path):
    store = ledger(tmp_path)
    store.ingest(
        [
            fact("parent", inclusion="rollup", tokens={"input": 1000, "output": 200}),
            fact("child", parentRequestId="parent"),
        ]
    )
    assert summarize(store)["tokens"]["total"] == 1200


def test_unrelated_session_parent_id_does_not_hide_usage(tmp_path):
    store = ledger(tmp_path)
    store.ingest(
        [
            fact("parent", inclusion="rollup"),
            fact("child", sourceSessionId="other", parentRequestId="parent"),
        ]
    )
    assert summarize(store)["tokens"]["total"] == 240


def test_snapshot_does_not_include_later_batch(tmp_path):
    store = ledger(tmp_path)
    store.ingest([fact()])
    report = summarize(store)
    store.ingest([fact("later")])
    snapshot = store.snapshot(report, "draft")
    assert len(snapshot["membership"]["batches"]) == 1
    assert snapshot["tokens"]["total"] == 120


def test_corrupt_saved_snapshot_is_not_trusted(tmp_path):
    import pytest

    from avo.cost_store import CostError, validate

    store = ledger(tmp_path)
    store.ingest([fact()])
    snapshot = store.snapshot(summarize(store), "draft")
    snapshot["tokens"]["total"] = 99999
    with pytest.raises(CostError, match="integrity"):
        validate("snapshot", snapshot)


def test_new_rate_does_not_silently_reprice_prior_unvalued_usage(tmp_path):
    store = ledger(tmp_path)
    store.ingest([fact(amounts=[])])
    store.price(
        {
            "schemaVersion": "1.0.0",
            "model": "model-a",
            "serviceProvider": "service-a",
            "unit": "USD",
            "basis": "calculated-estimate",
            "effectiveAt": "2026-10-22T00:00:00Z",
            "provenance": "fixture",
            "denominator": 1000,
            "rates": {"input": "1", "output": "2"},
        }
    )
    assert summarize(store)["amounts"] == []


def test_timestamp_offsets_cannot_apply_future_price(tmp_path):
    store = ledger(tmp_path)
    store.price(
        {
            "schemaVersion": "1.0.0",
            "model": "model-a",
            "serviceProvider": "service-a",
            "unit": "USD",
            "basis": "calculated-estimate",
            "effectiveAt": "2026-10-22T12:00:00-03:00",
            "provenance": "fixture",
            "denominator": 1000,
            "rates": {"input": "1", "output": "2"},
        }
    )
    store.ingest([fact(amounts=[], occurredAt="2026-10-22T14:00:00Z")])
    assert summarize(store)["amounts"] == []


def test_counters_do_not_duplicate_request_facts(tmp_path):
    store = ledger(tmp_path)
    store.ingest(
        [
            fact(),
            fact(
                "baseline", measurementKind="cumulative", counterEpoch="e1", sequence=1
            ),
            fact(
                "counter",
                measurementKind="cumulative",
                counterEpoch="e1",
                sequence=2,
                tokens={"input": 200, "output": 40},
            ),
        ]
    )
    assert summarize(store)["tokens"]["total"] == 120


def test_model_switch_in_counter_interval_preserves_known_tokens(tmp_path):
    store = ledger(tmp_path)
    store.ingest(
        [
            fact(
                "a",
                measurementKind="cumulative",
                counterEpoch="e1",
                sequence=1,
                tokens={"input": 100, "output": 10},
            ),
            fact(
                "b",
                model="new-model",
                measurementKind="cumulative",
                counterEpoch="e1",
                sequence=2,
                tokens={"input": 140, "output": 20},
            ),
        ]
    )
    report = summarize(store)
    assert report["tokens"]["total"] == 50
    assert "unknown" in report["breakdowns"]["model"]


def test_explicit_child_session_rollup_is_not_double_counted(tmp_path):
    store = ledger(tmp_path)
    store.ingest(
        [
            fact("parent", inclusion="rollup", tokens={"input": 1000, "output": 200}),
            fact(
                "child",
                sourceSessionId="child-session",
                parentSessionId="session",
                parentRequestId="parent",
            ),
        ]
    )
    assert summarize(store)["tokens"]["total"] == 1200


def test_v2_receipt_only_packet_is_committed_without_fake_usage(tmp_path):
    store = registered_ledger(tmp_path)
    terminal = receipt(
        lifecycle={"state": "closed", "reference": "a" * 64},
        flush={"status": "accepted", "reference": "a" * 64},
    )
    result = store.ingest_packet(
        packet(store, receipts=[terminal]), allow_synthetic=True
    )
    batches = store.capture()["batches"]
    assert result["batchId"]
    assert len(batches) == 1
    assert batches[0]["observations"] == []
    assert batches[0]["evidence"] == []
    assert batches[0]["receipts"] == [terminal]
    assert not store.path("receipts").exists()


def test_v2_known_row_keeps_new_evidence_without_double_counting(tmp_path):
    store = registered_ledger(tmp_path)
    row = fact()
    original = evidence(row)
    revised = evidence(row, acquisition="automatic")
    store.ingest_packet(
        packet(store, [row], evidence_rows=[original]), allow_synthetic=True
    )
    store.ingest_packet(
        packet(store, [row], evidence_rows=[revised], operation_id="packet-2"),
        allow_synthetic=True,
    )
    batches = store.capture()["batches"]
    accepted_ids = {
        item["evidenceId"] for batch in batches for item in batch["evidence"]
    }
    assert accepted_ids == {original["evidenceId"], revised["evidenceId"]}
    rows, _ = store.observations()
    assert len(rows) <= 1
    report = summarize(store)
    assert report["tokens"]["total"] is None
    assert report["observationCount"] == 0
    assert report["conflicts"]["tokens"]["total"] == 120


def test_v2_atomic_publish_failure_does_not_advance_receipt(tmp_path, monkeypatch):
    store = registered_ledger(tmp_path)
    row = fact()
    received = receipt(keys=[observation_key(row)])
    incoming = packet(store, [row], receipts=[received])
    original_publish = store._publish_locked

    def interrupted(target, value):
        if target.parent.name == "batches":
            raise OSError("synthetic interrupted commit")
        return original_publish(target, value)

    with monkeypatch.context() as scope:
        scope.setattr(store, "_publish_locked", interrupted)
        with pytest.raises((CostError, OSError)):
            store.ingest_packet(incoming, allow_synthetic=True)
    assert store.capture()["batches"] == []
    assert store.observations()[0] == []
    store.ingest_packet(incoming, allow_synthetic=True)
    assert len(store.capture()["batches"]) == 1
    assert store.capture()["batches"][0]["receipts"] == [received]


def test_v2_operation_replay_is_identical_and_changed_content_rejected(tmp_path):
    store = registered_ledger(tmp_path)
    incoming = packet(
        store, [fact()], receipts=[receipt(keys=[observation_key(fact())])]
    )
    first = store.ingest_packet(incoming, allow_synthetic=True)
    second = store.ingest_packet(incoming, allow_synthetic=True)
    assert second["batchId"] == first["batchId"]
    assert len(store.capture()["batches"]) == 1
    changed = packet(store, [fact("different")], operation_id=incoming["operationId"])
    with pytest.raises(CostError):
        store.ingest_packet(changed, allow_synthetic=True)
    assert len(store.capture()["batches"]) == 1


def test_v2_invalid_metadata_cannot_leave_observation_or_receipt(tmp_path):
    store = registered_ledger(tmp_path)
    row = fact()
    incoming = packet(store, [row], receipts=[receipt(keys=[observation_key(row)])])
    incoming["evidence"][0]["profileId"] = "f" * 64
    with pytest.raises(CostError):
        store.ingest_packet(incoming, allow_synthetic=True)
    assert store.capture()["batches"] == []
    assert store.observations()[0] == []


def test_v2_receipt_predecessor_branches_remain_visible(tmp_path):
    store = registered_ledger(tmp_path)
    start = receipt(watermark={"kind": "event", "value": "start"})
    left = receipt(
        predecessor=start["receiptId"], watermark={"kind": "event", "value": "left"}
    )
    right = receipt(
        predecessor=start["receiptId"], watermark={"kind": "event", "value": "right"}
    )
    for index, accepted in enumerate((start, left, right)):
        store.ingest_packet(
            packet(store, receipts=[accepted], operation_id=f"receipt-{index}"),
            allow_synthetic=True,
        )
    saved = [item for batch in store.capture()["batches"] for item in batch["receipts"]]
    assert {item["receiptId"] for item in saved} == {
        start["receiptId"],
        left["receiptId"],
        right["receiptId"],
    }
    report = summarize(store)
    assert report["coverage"] != "complete-for-declared-sources"
    assert any(
        "receipt" in str(item).lower() or "cursor" in str(item).lower()
        for item in report["diagnostics"]
    )


def _activity_decision(
    store, members, *, relation="same-activity", selected=None, **changes
):
    value = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": "activity-decision",
        "relation": relation,
        "references": [
            {"kind": "evidence", "id": item["evidenceId"]} for item in members
        ],
        "scope": members[0]["attribution"]["scope"],
        "selectedRepresentation": {"kind": "evidence", "id": selected["evidenceId"]}
        if selected
        else None,
        "actor": "synthetic-reviewer",
        "reason": "explicit source correlation proof",
        "proofRefs": [store.digest("synthetic-native-correlation")],
        "supersedes": [],
        "createdAt": FIXED_TIME,
    }
    value.update(changes)
    value["reconciliationId"] = store.digest(value)
    return value


def _ingest_activity(
    store, rows, metadata, *, accepted_profile=None, operation="activity-packet"
):
    accepted_profile = accepted_profile or profile()
    store.append_record("profiles", accepted_profile)
    incoming = packet(store, rows, evidence_rows=metadata, operation_id=operation)
    incoming["profileId"] = accepted_profile["profileId"]
    for received in incoming["receipts"]:
        received["profileId"] = accepted_profile["profileId"]
        received.pop("receiptId")
        received["receiptId"] = store.digest(received)
    return store.ingest_packet(incoming, allow_synthetic=True)


def test_us5_explicit_same_activity_selects_exact_membership_once(tmp_path):
    store = registered_ledger(tmp_path)
    rows = [fact("sdk"), fact("export", sourceInstanceId="synthetic-export")]
    metadata = [evidence(row) for row in rows]
    _ingest_activity(store, rows, metadata)
    before = store.snapshot(summarize(store), "draft")
    decision = _activity_decision(store, metadata, selected=metadata[0])
    store.append_record("reconciliations", decision)
    current = summarize(store)
    assert current["activityEvidenceIds"] == [metadata[0]["evidenceId"]]
    assert current["excludedEvidenceIds"] == [metadata[1]["evidenceId"]]
    assert current["selectedEvidenceIds"] == sorted(
        item["evidenceId"] for item in metadata
    )
    assert current["observationCount"] == 1
    assert current["tokens"]["total"] == 120
    assert current["amounts"] == [
        {"basis": "source-reported", "unit": "USD", "amount": "0.10"}
    ]
    assert (
        next(
            item
            for item in store.documents("snapshots")
            if item["snapshotId"] == before["snapshotId"]
        )
        == before
    )


def test_us5_identical_numbers_and_times_do_not_correlate_native_activities(tmp_path):
    store = registered_ledger(tmp_path)
    rows = [fact("first"), fact("second")]
    metadata = [evidence(row) for row in rows]
    _ingest_activity(store, rows, metadata)
    report = summarize(store)
    assert set(report["activityEvidenceIds"]) == {
        item["evidenceId"] for item in metadata
    }
    assert report["excludedEvidenceIds"] == []
    assert report["tokens"]["total"] == 240


@pytest.mark.parametrize("select_leaves", [False, True])
def test_us5_known_tree_selects_aggregate_or_complete_exact_leaves(
    tmp_path, select_leaves
):
    store = registered_ledger(tmp_path)
    semantics = {**profile()["semantics"], "aggregateScope": "tree"}
    frozen = profile(semantics=semantics)
    children = [
        fact("child-one", tokens={"total": 100}, amounts=[]),
        fact("child-two", tokens={"total": 140}, amounts=[]),
    ]
    child_metadata = []
    for index, row in enumerate(children):
        child_id = f"00000000-0000-4000-8000-0000000000{16 + index}"
        store.append_record(
            "participations",
            participation_fact(
                store,
                operation_id=f"child-{index}",
                participationId=child_id,
                agent={
                    "family": "codex",
                    "surface": "synthetic-export",
                    "version": "fixture-1",
                    "role": "subagent",
                    "parentParticipationId": PARTICIPATION_ID,
                },
            ),
        )
        child_metadata.append(
            evidence(row, participation_id=child_id, profile_id=frozen["profileId"])
        )
    aggregate = fact("tree", tokens={"total": 240}, amounts=[])
    aggregate_metadata = evidence(
        aggregate,
        profile_id=frozen["profileId"],
        aggregateScope={
            "kind": "tree",
            "members": [observation_key(row) for row in children],
            "proofRefs": [store.digest("native-complete-tree-membership")],
        },
    )
    members = [aggregate_metadata, *child_metadata]
    _ingest_activity(store, [aggregate, *children], members, accepted_profile=frozen)
    options = (
        {
            "selectedRepresentations": [
                {"kind": "evidence", "id": item["evidenceId"]}
                for item in child_metadata
            ]
        }
        if select_leaves
        else {}
    )
    decision = _activity_decision(
        store,
        members,
        relation="covers-rollup",
        selected=None if select_leaves else aggregate_metadata,
        **options,
    )
    store.append_record("reconciliations", decision)
    report = summarize(store)
    chosen, excluded = (
        (child_metadata, [aggregate_metadata])
        if select_leaves
        else ([aggregate_metadata], child_metadata)
    )
    assert set(report["activityEvidenceIds"]) == {item["evidenceId"] for item in chosen}
    assert set(report["excludedEvidenceIds"]) == {
        item["evidenceId"] for item in excluded
    }
    assert report["tokens"]["total"] == 240
    assert report["observationCount"] == len(chosen)
    assert set(report["breakdowns"]["agentRole"]) == {"subagent"}


def test_us5_unproved_tree_membership_does_not_silently_add_parent_and_children(
    tmp_path,
):
    store = registered_ledger(tmp_path)
    semantics = {**profile()["semantics"], "aggregateScope": "tree"}
    frozen = profile(semantics=semantics)
    rows = [
        fact("tree", tokens={"total": 240}),
        fact("child", parentRequestId="tree", tokens={"total": 100}),
    ]
    metadata = [
        evidence(
            rows[0],
            profile_id=frozen["profileId"],
            aggregateScope={"kind": "tree", "members": [], "proofRefs": []},
        ),
        evidence(rows[1], profile_id=frozen["profileId"]),
    ]
    _ingest_activity(store, rows, metadata, accepted_profile=frozen)
    report = summarize(store)
    assert report["activityEvidenceIds"] == []
    assert set(report["conflictEvidenceIds"]) == {
        item["evidenceId"] for item in metadata
    }
    assert report["tokens"]["total"] is None
    assert report["conflicts"]["tokens"]["total"] is None
    assert {item["tokens"]["total"] for item in report["representationConflicts"]} == {
        240,
        100,
    }
    assert any(
        item["code"] == "cost-aggregate-composition-unproven"
        for item in report["diagnostics"]
    )


def test_us5_copied_fork_new_ids_need_exact_inheritance_mapping(tmp_path):
    store = registered_ledger(tmp_path)
    frozen = profile(semantics={**profile()["semantics"], "fork": "copied-history"})
    original = fact("original")
    copied = fact(
        "new-fork-id",
        sourceSessionId="fork",
        parentSessionId="session",
        parentRequestId="original",
    )
    metadata = [
        evidence(row, profile_id=frozen["profileId"]) for row in (original, copied)
    ]
    _ingest_activity(store, [original, copied], metadata, accepted_profile=frozen)
    unresolved = summarize(store)
    assert unresolved["activityEvidenceIds"] == [metadata[0]["evidenceId"]]
    assert unresolved["unallocatedEvidenceIds"] == [metadata[1]["evidenceId"]]
    assert unresolved["tokens"]["total"] == 120
    store.append_record(
        "reconciliations", _activity_decision(store, metadata, selected=metadata[0])
    )
    resolved = summarize(store)
    assert resolved["activityEvidenceIds"] == [metadata[0]["evidenceId"]]
    assert resolved["excludedEvidenceIds"] == [metadata[1]["evidenceId"]]


def test_us5_shared_native_activity_requires_explicit_production_allocation(tmp_path):
    first, second = (
        registered_ledger(tmp_path / "first"),
        registered_ledger(tmp_path / "second"),
    )
    row = fact("shared-native-request")
    metadata = evidence(row)
    _ingest_activity(first, [row], [metadata])
    with pytest.raises(CostError, match="(scope|production|claim|allocation)"):
        _ingest_activity(second, [row], [metadata])
    allocation = _activity_decision(
        first,
        [metadata],
        relation="allocation",
        allocations=[
            {
                "accountingVideoId": second.identity()["accountingVideoId"],
                "scope": metadata["attribution"]["scope"],
                "reference": {"kind": "evidence", "id": metadata["evidenceId"]},
            }
        ],
    )
    first.append_record("reconciliations", allocation)
    _ingest_activity(second, [row], [metadata])
    assert summarize(first)["activityEvidenceIds"] == []
    assert summarize(first)["excludedEvidenceIds"] == [metadata["evidenceId"]]
    assert summarize(second)["activityEvidenceIds"] == [metadata["evidenceId"]]
    assert summarize(second)["tokens"]["total"] == 120


def test_us5_explicit_collected_fork_boundary_preserves_new_interval(tmp_path):
    from avo.cost_sources import collect_context
    from test_cost_sources import _automatic_context

    rows = [
        fact("copied", agent="fixture-executor", parentSessionId="old-session"),
        fact("new-work", agent="fixture-executor", parentSessionId="old-session"),
    ]
    store, context, *_ = _automatic_context(
        tmp_path,
        rows,
        source_shape="normalized-jsonl",
        fork="copied-history",
        boundary="copied",
    )
    assert collect_context(store, context)["imported"] == 1
    report = summarize(store)
    assert report["observationCount"] == 1
    assert report["tokens"]["total"] == 120
    assert report["unallocatedEvidenceIds"] == []
    assert report["activityEvidenceIds"] == [
        store.capture()["batches"][0]["evidence"][0]["evidenceId"]
    ]


def test_us5_cross_source_child_alias_remains_covered_by_proven_tree(tmp_path):
    store = registered_ledger(tmp_path)
    frozen = profile(semantics={**profile()["semantics"], "aggregateScope": "tree"})
    rows = [
        fact("tree", tokens={"total": 240}, amounts=[]),
        fact("child-one", tokens={"total": 100}, amounts=[]),
        fact("child-two", tokens={"total": 140}, amounts=[]),
        fact(
            "exported-child",
            sourceInstanceId="synthetic-export",
            tokens={"total": 100},
            amounts=[],
        ),
    ]
    metadata = [evidence(row, profile_id=frozen["profileId"]) for row in rows]
    metadata[0] = evidence(
        rows[0],
        profile_id=frozen["profileId"],
        aggregateScope={
            "kind": "tree",
            "members": [observation_key(row) for row in rows[1:3]],
            "proofRefs": [store.digest("known-native-membership")],
        },
    )
    _ingest_activity(store, rows, metadata, accepted_profile=frozen)
    store.append_record(
        "reconciliations",
        _activity_decision(store, [metadata[1], metadata[3]], selected=metadata[3]),
    )
    report = summarize(store)
    assert report["activityEvidenceIds"] == [metadata[0]["evidenceId"]]
    assert set(report["excludedEvidenceIds"]) == {
        item["evidenceId"] for item in metadata[1:]
    }
    assert report["conflictEvidenceIds"] == []
    assert report["tokens"]["total"] == 240


def test_us5_activity_selection_handles_long_explicit_chains_without_recursion():
    from avo.costs import _resolve_activity_choices

    indexed = {str(index): None for index in range(2000)}
    choices = {str(index): {frozenset({str(index + 1)})} for index in range(1999)}
    selected, conflicts = _resolve_activity_choices(indexed, choices, set())
    assert selected == {"1999"}
    assert conflicts == set()
