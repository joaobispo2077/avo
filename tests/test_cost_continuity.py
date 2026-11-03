"""Synthetic, offline fixtures for accounting across host and source changes."""

import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Lock

import pytest

from avo.cost_store import CostStore
from avo.timeline.contracts import content_hash
from test_costs import fact
from test_costs_cli import project

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "costs" / "continuity"
FIXED_TIME = "2026-10-31T12:00:00Z"
PARTICIPATION_ID = "00000000-0000-4000-8000-000000000015"


def test_expected_intervals_keep_handoff_gap_separate_from_source_grant(
    tmp_path, offline_accounting
):
    from avo.cost_participation import (
        expected_participation_intervals,
        register_context,
        transition_context,
    )

    store, _ = production(tmp_path)
    first = register_context(store, host_descriptor("first"))
    second = register_context(store, host_descriptor("second", "claude"))
    end_a = {"kind": "event", "reference": "a-ended"}
    end_b = {"kind": "event", "reference": "b-ended"}
    start_a = {"kind": "event", "reference": "a-resumed"}
    closed = transition_context(
        store,
        transition_request(
            store, first["participationId"], second["participationId"], boundary=end_a
        ),
    )
    transition_context(
        store,
        transition_request(
            store,
            second["participationId"],
            first["participationId"],
            operationId="b-to-a",
            boundary=end_b,
        ),
    )
    resumed = transition_context(
        store,
        transition_request(
            store,
            first["participationId"],
            first["participationId"],
            operationId="a-resume",
            kind="resume",
            boundary=start_a,
        ),
    )
    expected = expected_participation_intervals(store.capture()["participations"])
    intervals = expected[first["participationId"]]
    assert len(intervals) == 2
    assert intervals[0]["scope"]["beginning"] == {
        "kind": "event",
        "reference": "beginning",
    }
    assert intervals[0]["scope"]["ending"] == end_a
    assert intervals[0]["lifecycle"] == "closed"
    assert intervals[0]["endFactId"] == closed["factId"]
    assert intervals[1]["scope"]["beginning"] == start_a
    assert "ending" not in intervals[1]["scope"]
    assert intervals[1]["startFactId"] == resumed["factId"]
    assert all(not item["conflicted"] for item in intervals)
    # The source grant remains reusable; it is not a claim of continuous responsibility.
    current = host_descriptor("first")
    current["operationId"] = "current-revise"
    revised = register_context(store, current)
    assert revised["participationId"] == first["participationId"]


def test_expected_intervals_never_turn_uncertain_time_into_owned_boundary(
    tmp_path, offline_accounting
):
    from avo.cost_participation import (
        expected_participation_intervals,
        register_context,
        transition_context,
    )

    store, _ = production(tmp_path)
    first = register_context(store, host_descriptor("first"))
    second = register_context(store, host_descriptor("second", "claude"))
    boundary = {"kind": "uncertain", "at": "2026-10-31T12:00:00Z"}
    transition_context(
        store,
        transition_request(
            store,
            first["participationId"],
            second["participationId"],
            kind="boundary-unknown",
            boundary=boundary,
        ),
    )
    interval = expected_participation_intervals(store.capture()["participations"])[
        first["participationId"]
    ][0]
    assert interval["lifecycle"] == "unknown"
    assert interval["scope"]["ending"] == boundary
    assert interval["scope"]["ending"]["kind"] != "event"


def test_expected_intervals_preserve_conflicting_native_endpoints(
    tmp_path, offline_accounting
):
    from avo.cost_participation import (
        build_participation_fact,
        expected_participation_intervals,
        register_context,
    )

    store, _ = production(tmp_path)
    first = register_context(store, host_descriptor("first"))
    target = register_context(store, host_descriptor("target", "claude"))
    ends = []
    for suffix, stamp in (
        ("left", "2026-11-02T12:00:00Z"),
        ("right", "2026-10-30T12:00:00Z"),
    ):
        payload = {
            "schemaVersion": "2.0.0",
            "accountingVideoId": store.identity()["accountingVideoId"],
            "participationId": first["participationId"],
            "operationId": suffix,
            "kind": "transition",
            "createdAt": stamp,
            "predecessors": [first["factId"], target["factId"]],
            "actor": "synthetic-reviewer",
            "provenance": {
                "producer": "fixture",
                "reference": "explicit native endpoint",
            },
            "fromParticipationId": first["participationId"],
            "toParticipationId": target["participationId"],
            "transitionKind": "sequential",
            "boundary": {"kind": "event", "reference": suffix},
            "lifecycle": "closed",
        }
        ends.append(
            store.append_record("participations", build_participation_fact(payload))[
                "factId"
            ]
        )
    interval = expected_participation_intervals(store.capture()["participations"])[
        first["participationId"]
    ][0]
    assert interval["conflicted"] is True
    assert interval["lifecycle"] == "unknown"
    assert set(ends).issubset(interval["factIds"])
    assert interval["scope"]["ending"]["kind"] == "unknown"


def load_manifest():
    return json.loads((FIXTURE_DIR / "manifest.json").read_text("utf-8"))


def context_descriptor(**changes):
    value = {
        "schemaVersion": "2.0.0",
        "operationId": "context-1",
        "mode": "agent",
        "agent": {
            "family": "codex",
            "surface": "synthetic-export",
            "version": "fixture-1",
            "role": "driver",
            "sourceSessionId": "session",
        },
        "scope": {
            "runAliases": ["fixture-run"],
            "sourceInstanceId": "synthetic",
            "sourceSessionId": "session",
            "counterEpoch": None,
            "beginning": {"kind": "event", "reference": "beginning"},
        },
        "provenance": {"producer": "synthetic-test", "reference": "fixture"},
    }
    value.update(changes)
    return value


def transition_request(store, source, target=None, **changes):
    value = {
        "schemaVersion": "2.0.0",
        "operationId": "transition-1",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "fromParticipationId": source,
        "kind": "sequential",
        "boundary": {"kind": "event", "reference": "handoff-event"},
        "actor": "synthetic-test",
        "reason": "explicit synthetic handoff",
    }
    if target is not None:
        value["toParticipationId"] = target
    value.update(changes)
    return value


def host_descriptor(name, agent="codex", *, parent=None):
    descriptor = context_descriptor(operationId="context-" + name)
    descriptor["agent"].update(family=agent, sourceSessionId=name + "-session")
    if parent:
        descriptor["agent"].update(role="subagent", parentParticipationId=parent)
    descriptor["scope"].update(
        sourceInstanceId=name + "-source",
        sourceSessionId=name + "-session",
        runAliases=[name + "-run"],
    )
    return descriptor


def observation_key(row):
    return CostStore.keys_for([row])[0]


def profile(**changes):
    """Test-qualified only: never a declaration of vendor support."""
    value = {
        "schemaVersion": "2.0.0",
        "agent": "codex",
        "surface": "synthetic-export",
        "versions": ["fixture-1"],
        "sourceFormat": "synthetic-normalized-v2",
        "parserVersion": "fixture-1",
        "parserDigest": content_hash("synthetic-parser-1"),
        "fixtureDigests": [content_hash(fact())],
        "references": [{"url": "https://avo.local/synthetic", "date": "2026-10-31"}],
        "capability": "qualified",
        "semantics": {
            "counter": "request",
            "categoryOverlap": {"cacheRead": "input", "reasoning": "output"},
            "aggregateScope": "request",
            "revision": "immutable",
            "resume": "new-activities",
            "fork": "new-activities",
            "reset": "not-applicable",
            "finality": "source-flush",
        },
        "identityFields": ["requestId"],
        "allowedFields": ["tokens"],
        "limitations": [],
        "qualification": {
            "kind": "synthetic",
            "evidenceRefs": [content_hash("synthetic-qualification")],
        },
    }
    value.update(changes)
    value.pop("profileId", None)
    value["profileId"] = content_hash(value)
    return value


def evidence(row, *, participation_id=PARTICIPATION_ID, profile_id=None, **changes):
    value = {
        "key": observation_key(row),
        "participationId": participation_id,
        "profileId": profile_id or profile()["profileId"],
        "nature": "measured",
        "acquisition": "imported",
        "sourceEventId": row["requestId"],
        "interval": {
            "sourceSessionId": row["sourceSessionId"],
            "counterEpoch": row.get("counterEpoch"),
            "start": {"kind": "event", "reference": row["requestId"]},
            "end": {"kind": "event", "reference": row["requestId"]},
        },
        "attribution": {
            "status": "assigned",
            "basis": "explicit synthetic source binding",
            "scope": {"runAliases": ["fixture-run"], "beginning": {"kind": "declared"}},
        },
        "modelBasis": "served",
        "aggregateScope": {"kind": "request", "members": [], "proofRefs": []},
    }
    value.update(changes)
    value.pop("evidenceId", None)
    value["evidenceId"] = content_hash(
        {"domain": "cost-evidence/v2", "metadata": value}
    )
    return value


def receipt(*, profile_id=None, predecessor=None, keys=None, **changes):
    value = {
        "profileId": profile_id or profile()["profileId"],
        "bindingId": None,
        "sourceInstanceId": "synthetic",
        "sourceSessionId": "session",
        "predecessorReceiptId": predecessor,
        "counterEpoch": None,
        "watermark": {"kind": "event", "value": "r1"},
        "observationKeys": keys or [],
        "baseline": {"status": "not-applicable", "reference": None},
        "lifecycle": {"state": "open", "reference": None},
        "flush": {"status": "unknown", "reference": None},
        "interval": {
            "sourceSessionId": "session",
            "counterEpoch": None,
            "start": {"kind": "declared"},
            "end": {"kind": "event", "reference": "r1"},
        },
        "gaps": [],
        "collectedAt": FIXED_TIME,
    }
    value.update(changes)
    if "interval" not in changes:
        value["interval"]["sourceSessionId"] = value["sourceSessionId"]
        value["interval"]["counterEpoch"] = value["counterEpoch"]
    value.pop("receiptId", None)
    value["receiptId"] = content_hash(value)
    return value


def packet(
    store, rows=None, *, evidence_rows=None, receipts=None, operation_id="packet-1"
):
    rows = deepcopy(rows or [])
    if receipts is None:
        grouped = {}
        for row in rows:
            lineage = (
                row["sourceInstanceId"],
                row["sourceSessionId"],
                row.get("counterEpoch"),
            )
            grouped.setdefault(lineage, []).append(observation_key(row))
        receipts = [
            receipt(
                sourceInstanceId=source,
                sourceSessionId=session,
                counterEpoch=epoch,
                keys=keys,
            )
            for (source, session, epoch), keys in grouped.items()
        ]
        if not receipts:
            receipts = [receipt()]
    return {
        "schemaVersion": "2.0.0",
        "operationId": operation_id,
        "accountingVideoId": store.identity()["accountingVideoId"],
        "profileId": profile()["profileId"],
        "observations": rows,
        "evidence": deepcopy(
            evidence_rows
            if evidence_rows is not None
            else [evidence(row) for row in rows]
        ),
        "receipts": deepcopy(receipts),
    }


def production(tmp_path, *, name="video-a"):
    root = tmp_path / name
    root.mkdir(parents=True)
    project_path = project(root)
    store = CostStore(root)
    store.initialize("channel", name)
    return store, project_path


def participation_fact(store, *, operation_id="declare-1", **changes):
    value = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "participationId": PARTICIPATION_ID,
        "operationId": operation_id,
        "kind": "declare",
        "createdAt": FIXED_TIME,
        "predecessors": [],
        "actor": "synthetic-test",
        "provenance": {"producer": "synthetic-test", "reference": "fixture"},
        "agent": {
            "family": "codex",
            "surface": "synthetic-export",
            "version": "fixture-1",
            "role": "driver",
        },
        "scope": {"runAliases": ["fixture-run"], "beginning": {"kind": "declared"}},
        "mode": "agent",
    }
    value.update(changes)
    value.pop("factId", None)
    value["factId"] = content_hash(value)
    return value


def registered_ledger(tmp_path):
    store, _ = production(tmp_path)
    store.append_record("profiles", profile())
    store.append_record("participations", participation_fact(store))
    return store


def reconciliation(store, old, new, **changes):
    value = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": "reconcile-1",
        "relation": "revises-evidence",
        "references": [
            {"kind": "evidence", "id": item["evidenceId"]} for item in (old, new)
        ],
        "scope": old["attribution"]["scope"],
        "selectedRepresentation": {"kind": "evidence", "id": new["evidenceId"]},
        "oldEvidenceId": old["evidenceId"],
        "newEvidenceId": new["evidenceId"],
        "actor": "synthetic-reviewer",
        "reason": "verified exact original source metadata",
        "proofRefs": [content_hash("synthetic-proof")],
        "supersedes": [],
        "createdAt": FIXED_TIME,
    }
    value.update(changes)
    value.pop("reconciliationId", None)
    value["reconciliationId"] = content_hash(value)
    return value


@pytest.fixture
def offline_accounting(monkeypatch, tmp_path):
    """Prevent media/network execution and isolate the host's local registry."""
    from avo import avo_state, cost_store

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "offline accounting must not run network, inference or render"
        )

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cost_store, "now_iso", lambda: FIXED_TIME)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    return {"state": tmp_path / "state", "forbidden": forbidden}


def test_continuity_manifest_is_synthetic_and_frozen():
    manifest = load_manifest()
    raw = (FIXTURE_DIR / manifest["legacyFixture"]).read_bytes()
    assert sha256(raw).hexdigest() == manifest["legacyFixtureSha256"]
    assert manifest["provenance"] == "synthetic; no private source or paid inference"
    assert manifest["legacy"]["hostCoverage"] == "unknown"


def test_productions_and_sources_are_isolated(tmp_path, offline_accounting):
    first, first_project = production(tmp_path)
    second, second_project = production(tmp_path, name="video-b")
    assert (
        first.identity()["accountingVideoId"] != second.identity()["accountingVideoId"]
    )
    assert first_project != second_project
    source = first.raw_dir / "synthetic-source.json"
    source.write_text(json.dumps([fact()]), encoding="utf-8")
    source.unlink()
    assert not source.exists()
    assert first.identity()["createdAt"] == FIXED_TIME
    assert not offline_accounting["state"].exists()


def test_evidence_ids_are_domain_separated_and_metadata_specific():
    from avo.cost_participation import evidence_id, legacy_evidence_id

    first = evidence(fact())
    other = evidence(fact(), acquisition="automatic")
    assert evidence_id(first) == first["evidenceId"]
    assert evidence_id(other) != first["evidenceId"]
    assert legacy_evidence_id(first["key"]) == content_hash(
        {"domain": "legacy-unknown/v1", "key": first["key"]}
    )
    assert legacy_evidence_id(first["key"]) != first["evidenceId"]


def test_participation_builder_is_pure_and_replay_requires_same_content(tmp_path):
    from avo.cost_participation import build_participation_fact, validate_fact_graph

    store, _ = production(tmp_path)
    supplied = participation_fact(store)
    original = deepcopy(supplied)
    assert build_participation_fact(supplied) == supplied
    assert supplied == original
    validate_fact_graph([supplied, deepcopy(supplied)])
    changed = participation_fact(store, reason="a different declaration")
    with pytest.raises(ValueError, match="operation|replay"):
        validate_fact_graph([supplied, changed])


def test_participation_rejects_unknown_predecessor_and_parent_cycle(tmp_path):
    from avo.cost_participation import validate_fact_graph

    store, _ = production(tmp_path)
    bad = participation_fact(store, predecessors=["f" * 64])
    with pytest.raises(ValueError, match="predecessor"):
        validate_fact_graph([bad])
    first_id = PARTICIPATION_ID
    second_id = "00000000-0000-4000-8000-000000000016"
    first = participation_fact(
        store,
        agent={
            "family": "codex",
            "surface": "synthetic-export",
            "version": "fixture-1",
            "role": "subagent",
            "parentParticipationId": second_id,
        },
    )
    second = participation_fact(
        store,
        operation_id="declare-2",
        participationId=second_id,
        agent={
            "family": "claude",
            "surface": "synthetic-export",
            "version": "fixture-1",
            "role": "subagent",
            "parentParticipationId": first_id,
        },
    )
    with pytest.raises(ValueError, match="cycle"):
        validate_fact_graph([first, second])


def test_evidence_variants_require_explicit_revision(tmp_path):
    from avo.cost_participation import resolve_evidence, validate_reconciliation

    store, _ = production(tmp_path)
    original = evidence(fact())
    revised = evidence(fact(), acquisition="automatic")
    unresolved = resolve_evidence([original, revised], [])
    assert unresolved["selected"] == []
    assert unresolved["conflicts"]
    decision = reconciliation(store, original, revised)
    validate_reconciliation(
        decision, known_refs={item["evidenceId"]: item for item in (original, revised)}
    )
    resolved = resolve_evidence([original, revised], [decision])
    assert resolved == {"selected": [revised], "conflicts": []}


def test_evidence_revision_cannot_change_observation_payload(tmp_path):
    from avo.cost_participation import validate_reconciliation

    store, _ = production(tmp_path)
    original = evidence(fact())
    other_row = evidence(fact(model="different-served-model"))
    decision = reconciliation(store, original, other_row)
    with pytest.raises(ValueError, match="observation|key|payload"):
        validate_reconciliation(
            decision,
            known_refs={item["evidenceId"]: item for item in (original, other_row)},
        )


def test_competing_evidence_decisions_need_explicit_supersession(tmp_path):
    from avo.cost_participation import resolve_evidence

    store, _ = production(tmp_path)
    original = evidence(fact())
    first = evidence(fact(), acquisition="automatic")
    second = evidence(fact(), nature="manual")
    left = reconciliation(store, original, first)
    right = reconciliation(store, original, second, operationId="reconcile-2")
    variants = [original, first, second]
    assert resolve_evidence(variants, [left, right])["conflicts"]
    final = reconciliation(
        store,
        first,
        second,
        operationId="reconcile-3",
        supersedes=[left["reconciliationId"], right["reconciliationId"]],
    )
    # The explicit final choice must cover every retained variant, including original.
    direct = reconciliation(
        store,
        original,
        second,
        operationId="reconcile-4",
        supersedes=[left["reconciliationId"], right["reconciliationId"]],
    )
    assert resolve_evidence(variants, [left, right, final, direct]) == {
        "selected": [second],
        "conflicts": [],
    }


def test_context_replay_does_not_depend_on_generated_time(
    tmp_path, monkeypatch, offline_accounting
):
    from avo import avo_state
    from avo.cost_participation import register_context

    store, _ = production(tmp_path)
    descriptor = context_descriptor()
    first = register_context(store, descriptor)
    monkeypatch.setattr(avo_state, "now_iso", lambda: "2026-11-01T12:00:00Z")
    second = register_context(store, descriptor)
    assert second["participationId"] == first["participationId"]
    assert second["factId"] == first["factId"]
    assert second["replayed"] is True
    assert len(store.capture()["participations"]) == 1
    with pytest.raises(ValueError, match="operation|replay"):
        register_context(store, context_descriptor(mode="identity-unknown"))


def test_context_reuses_only_explicit_current_session_and_scope(
    tmp_path, offline_accounting
):
    from avo.cost_participation import register_context

    store, _ = production(tmp_path)
    first = register_context(store, context_descriptor())
    second = register_context(store, context_descriptor(operationId="context-2"))
    assert second["participationId"] == first["participationId"]
    other = context_descriptor(operationId="context-3")
    other["agent"]["sourceSessionId"] = "different-session"
    other["scope"]["sourceSessionId"] = "different-session"
    third = register_context(store, other)
    assert third["participationId"] != first["participationId"]
    absent = register_context(
        store, None, run_alias="same-run", operation_id="unknown-entry"
    )
    assert absent["participationId"] not in {
        first["participationId"],
        third["participationId"],
    }
    saved = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == absent["factId"]
    )
    assert saved["mode"] == "identity-unknown"


def test_context_optional_source_denial_preserves_expected_host(
    tmp_path, offline_accounting
):
    from avo.cost_participation import register_context

    store, _ = production(tmp_path)
    denied = context_descriptor(
        sourceAttachment={
            "bindingId": "not-authorized",
            "profileId": profile()["profileId"],
        }
    )
    result = register_context(store, denied)
    assert result["status"] == "ok"
    assert result["diagnostics"]
    declaration = store.capture()["participations"][0]
    assert declaration["agent"]["family"] == "codex"
    assert "sourceAttachment" not in declaration


def test_context_human_ci_requires_a_bounded_explicit_scope(
    tmp_path, offline_accounting
):
    from avo.cost_participation import register_context

    store, _ = production(tmp_path)
    descriptor = context_descriptor(mode="human-ci")
    with pytest.raises(ValueError, match="bound|ending|scope"):
        register_context(store, descriptor)
    assert store.capture()["participations"] == []
    descriptor["scope"]["ending"] = {"kind": "event", "reference": "finished"}
    result = register_context(store, descriptor)
    assert result["participationId"]
    assert store.capture()["participations"][0]["kind"] == "declare-no-external-agent"


def test_context_reuses_existing_authority_without_reading_source(
    tmp_path, offline_accounting
):
    from avo.cost_participation import register_context

    store, _ = production(tmp_path)
    frozen_profile = store.append_record("profiles", profile())
    source = store.raw_dir / "authorized-synthetic-source.json"
    source.write_text(json.dumps([fact()]), encoding="utf-8")
    binding = store.bind(
        source=source, agent="codex", session_id="session", boundary="beginning"
    )
    attachment = {
        "bindingId": binding["bindingId"],
        "profileId": frozen_profile["profileId"],
    }
    first = register_context(store, context_descriptor(sourceAttachment=attachment))
    descriptor = context_descriptor(operationId="another-entry")
    descriptor["scope"]["runAliases"] = ["another-run"]
    # Source availability belongs to collection, not identity registration.
    source.unlink()
    second = register_context(store, descriptor)
    assert second["participationId"] == first["participationId"]
    assert second["diagnostics"] == []
    assert len(store.capture()["bindings"]) == 1
    latest = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == second["factId"]
    )
    assert latest["sourceAttachment"] == attachment
    assert latest["scope"]["runAliases"] == ["another-run", "fixture-run"]


def test_concurrent_context_replay_publishes_one_fact(
    tmp_path, monkeypatch, offline_accounting
):
    from avo import avo_state
    from avo.cost_participation import register_context

    store, _ = production(tmp_path)
    barrier = Barrier(2)
    clock_lock = Lock()
    stamps = iter(["2026-10-31T12:00:01Z", "2026-10-31T12:00:02Z"])
    original_append = store.append_record

    def unique_clock():
        with clock_lock:
            return next(stamps)

    def publish_together(kind, payload):
        barrier.wait(timeout=10)
        return original_append(kind, payload)

    monkeypatch.setattr(avo_state, "now_iso", unique_clock)
    monkeypatch.setattr(store, "append_record", publish_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: register_context(store, context_descriptor()), range(2))
        )
    assert len(store.capture()["participations"]) == 1
    assert len({result["participationId"] for result in results}) == 1
    assert len({result["factId"] for result in results}) == 1
    assert sorted(result["replayed"] for result in results) == [False, True]


def test_transition_known_boundary_closes_only_previous_scope(
    tmp_path, offline_accounting
):
    from avo.cost_participation import (
        project_participation_facts,
        register_context,
        transition_context,
    )

    store, _ = production(tmp_path)
    first = register_context(store, host_descriptor("first"))
    second = register_context(store, host_descriptor("second", "claude"))
    request = transition_request(
        store, first["participationId"], second["participationId"]
    )
    accepted = transition_context(store, request)
    replay = transition_context(store, request)
    assert replay["factId"] == accepted["factId"]
    assert replay["replayed"] is True
    states = {
        item["participationId"]: item
        for item in project_participation_facts(store.capture()["participations"])[
            "participations"
        ]
    }
    assert states[first["participationId"]]["scope"]["ending"] == request["boundary"]
    assert states[first["participationId"]]["lifecycle"] == "closed"
    assert "ending" not in states[second["participationId"]]["scope"]
    with pytest.raises(ValueError, match="operation|replay"):
        transition_context(store, {**request, "reason": "different content"})


def test_transition_unknown_boundary_and_new_device_do_not_borrow_baseline(
    tmp_path, offline_accounting
):
    from avo.cost_participation import (
        project_participation_facts,
        register_context,
        transition_context,
    )

    store, _ = production(tmp_path)
    first = register_context(store, host_descriptor("first"))
    request = transition_request(
        store,
        first["participationId"],
        declaration=host_descriptor("new-device", "claude"),
        kind="boundary-unknown",
        boundary={"kind": "uncertain", "at": FIXED_TIME},
        baselineRef="f" * 64,
    )
    result = transition_context(store, request)
    assert result["diagnostics"]
    assert result["toParticipationId"] != first["participationId"]
    saved = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == result["factId"]
    )
    assert saved.get("baselineRef") is None
    old = next(
        item
        for item in project_participation_facts(store.capture()["participations"])[
            "participations"
        ]
        if item["participationId"] == first["participationId"]
    )
    assert "ending" not in old["scope"]
    assert old["lifecycle"] == "unknown"


def test_delegation_keeps_parent_and_requires_explicit_child_lineage(
    tmp_path, offline_accounting
):
    from avo.cost_participation import (
        project_participation_facts,
        register_context,
        transition_context,
    )

    store, _ = production(tmp_path)
    parent = register_context(store, host_descriptor("parent"))
    request = transition_request(
        store,
        parent["participationId"],
        declaration=host_descriptor(
            "child", "claude", parent=parent["participationId"]
        ),
        kind="delegation",
    )
    result = transition_context(store, request)
    states = {
        item["participationId"]: item
        for item in project_participation_facts(store.capture()["participations"])[
            "participations"
        ]
    }
    assert states[parent["participationId"]]["lifecycle"] == "open"
    child = states[result["toParticipationId"]]
    assert child["agent"]["role"] == "subagent"
    assert child["agent"]["parentParticipationId"] == parent["participationId"]
    invalid = transition_request(
        store,
        parent["participationId"],
        declaration=host_descriptor("unrelated", "claude"),
        operationId="invalid-delegation",
        kind="delegation",
    )
    before = store.capture()["participations"]
    with pytest.raises(ValueError, match="child|parent|delegation"):
        transition_context(store, invalid)
    assert store.capture()["participations"] == before


def test_explicit_merge_resolves_frontier_conflict_without_clock_order(
    tmp_path, offline_accounting
):
    from avo.cost_participation import (
        build_participation_fact,
        project_participation_facts,
        register_context,
    )

    store, _ = production(tmp_path)
    original = register_context(store, host_descriptor("first"))
    base = store.capture()["participations"][0]
    variants = []
    for suffix, stamp in (
        ("left", "2026-11-02T12:00:00Z"),
        ("right", "2026-10-30T12:00:00Z"),
    ):
        value = deepcopy(base)
        value.pop("factId")
        value.update(
            kind="revise",
            operationId=suffix,
            createdAt=stamp,
            predecessors=[base["factId"]],
        )
        value["agent"]["selectedModel"] = suffix
        variants.append(
            store.append_record("participations", build_participation_fact(value))
        )
    conflicted = project_participation_facts(store.capture()["participations"])
    assert conflicted["conflicts"]
    assert conflicted["participations"][0]["conflicted"] is True
    merged = deepcopy(base)
    merged.pop("factId")
    merged.update(
        kind="revise",
        operationId="explicit-merge",
        predecessors=[item["factId"] for item in variants],
    )
    merged["agent"]["selectedModel"] = "reviewed-selection"
    store.append_record("participations", build_participation_fact(merged))
    resolved = project_participation_facts(store.capture()["participations"])
    assert resolved["conflicts"] == []
    assert (
        resolved["participations"][0]["agent"]["selectedModel"] == "reviewed-selection"
    )
    assert (
        resolved["participations"][0]["participationId"] == original["participationId"]
    )


def test_resume_and_selected_model_revision_preserve_source_history(
    tmp_path, offline_accounting
):
    from avo.cost_participation import (
        project_participation_facts,
        register_context,
        transition_context,
    )

    store, _ = production(tmp_path)
    initial = host_descriptor("first")
    original = register_context(store, initial)
    request = transition_request(
        store, original["participationId"], original["participationId"], kind="resume"
    )
    transition_context(store, request)
    revised = deepcopy(initial)
    revised["operationId"] = "selected-model-update"
    revised["agent"]["selectedModel"] = "new-selected-hint"
    updated = register_context(store, revised)
    assert updated["participationId"] == original["participationId"]
    original_fact = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == original["factId"]
    )
    assert original_fact["agent"].get("selectedModel") is None
    state = project_participation_facts(store.capture()["participations"])[
        "participations"
    ][0]
    assert state["agent"]["selectedModel"] == "new-selected-hint"
    assert state["scope"]["sourceInstanceId"] == "first-source"


def test_manifest_three_agents_four_models_two_resumes_preserves_exact_usage(
    tmp_path, offline_accounting
):
    from avo.cost_participation import register_context, transition_context
    from avo.costs import summarize

    store, _ = production(tmp_path)
    scenario = load_manifest()["scenarios"]["handoffResumes"]
    participants = {}
    for name, agent in (
        ("first", "codex"),
        ("second", "claude"),
        ("third", "opencode"),
    ):
        participants[name] = register_context(store, host_descriptor(name, agent))[
            "participationId"
        ]
    for index, (source, target, kind) in enumerate(
        (
            ("first", "second", "sequential"),
            ("second", "second", "resume"),
            ("second", "third", "sequential"),
            ("third", "third", "resume"),
        )
    ):
        transition_context(
            store,
            transition_request(
                store,
                participants[source],
                participants[target],
                operationId=f"handoff-{index}",
                kind=kind,
            ),
        )
    for name, agent in (("child-one", "codex"), ("child-two", "opencode")):
        accepted = transition_context(
            store,
            transition_request(
                store,
                participants["third"],
                declaration=host_descriptor(name, agent, parent=participants["third"]),
                operationId="delegate-" + name,
                kind="delegation",
            ),
        )
        participants[name] = accepted["toParticipationId"]
    changed = host_descriptor("third", "opencode")
    changed["operationId"] = "router-selected-model-update"
    changed["agent"]["selectedModel"] = "selected-only-never-served"
    assert register_context(store, changed)["participationId"] == participants["third"]
    prices = {}
    for model in ("model-a", "model-b", "model-c", "model-d"):
        price = {
            "schemaVersion": "1.0.0",
            "model": model,
            "serviceProvider": "fixture-api",
            "unit": scenario["unit"],
            "basis": "calculated-estimate",
            "provenance": "fixed synthetic tariff",
            "effectiveAt": "2026-10-01T00:00:00Z",
            "denominator": scenario["price"]["denominator"],
            "rates": {key: scenario["price"][key] for key in ("input", "output")},
        }
        prices[model] = store.price(price)
    profiles = {
        agent: store.append_record("profiles", profile(agent=agent))
        for agent in ("codex", "claude", "opencode")
    }
    expected_keys = []
    previous_receipts = {}
    for activity in scenario["activities"]:
        name = activity["participant"]
        row = fact(
            activity["requestId"],
            agent=activity["agent"],
            model=activity["model"],
            sourceInstanceId=name + "-source",
            sourceSessionId=name + "-session",
            serviceProvider="fixture-api",
            phase=activity["phase"],
            tokens={key: activity[key] for key in ("input", "output")},
            semantics={},
            amounts=[],
        )
        frozen_profile = profiles[activity["agent"]]
        identity = frozen_profile["profileId"]
        metadata = evidence(
            row,
            participation_id=participants[name],
            profile_id=identity,
            attribution={
                "status": "assigned",
                "basis": "explicit manifest activity",
                "scope": host_descriptor(name, activity["agent"])["scope"],
            },
        )
        received = receipt(
            profile_id=identity,
            predecessor=previous_receipts.get(name),
            sourceInstanceId=row["sourceInstanceId"],
            sourceSessionId=row["sourceSessionId"],
            keys=[observation_key(row)],
            watermark={"kind": "event", "value": row["requestId"]},
        )
        previous_receipts[name] = received["receiptId"]
        incoming = packet(
            store,
            [row],
            evidence_rows=[metadata],
            receipts=[received],
            operation_id="activity-" + row["requestId"],
        )
        incoming["profileId"] = identity
        store.ingest_packet(incoming, allow_synthetic=True)
        store.ingest_packet(incoming, allow_synthetic=True)
        expected_keys.append(observation_key(row))
    report = summarize(store)
    assert report["tokens"]["total"] == scenario["uniqueTokens"]
    assert report["amounts"] == [
        {
            "basis": "calculated-estimate",
            "unit": scenario["unit"],
            "amount": scenario["amount"],
        }
    ]
    rows, _ = store.observations()
    assert {row["requestId"]: row["model"] for row in rows} == {
        item["requestId"]: item["model"] for item in scenario["activities"]
    }
    accepted_keys = [
        key for batch in store.capture()["batches"] for key in batch["observationKeys"]
    ]
    assert {content_hash(key) for key in accepted_keys} == {
        content_hash(key) for key in expected_keys
    }
    assert set(report["breakdowns"]["agent"]) == {"codex", "claude", "opencode"}
    assert set(report["breakdowns"]["model"]) == set(prices)
    snapshot = store.snapshot(report, "draft")
    original_bytes = store.path(
        "snapshots/" + snapshot["snapshotId"] + ".json"
    ).read_bytes()
    store.price(
        {
            "schemaVersion": "1.0.0",
            "model": "model-a",
            "serviceProvider": "fixture-api",
            "unit": "USD",
            "basis": "calculated-estimate",
            "provenance": "later synthetic configuration",
            "effectiveAt": "2026-10-02T00:00:00Z",
            "denominator": 1000,
            "rates": {"input": "100", "output": "100"},
        }
    )
    assert summarize(store)["amounts"] == report["amounts"]
    assert (
        store.path("snapshots/" + snapshot["snapshotId"] + ".json").read_bytes()
        == original_bytes
    )
    facts = store.capture()["participations"]
    assert (
        sum(item.get("transitionKind") == "resume" for item in facts)
        == scenario["resumes"]
    )
    assert (
        sum(item.get("transitionKind") == "delegation" for item in facts)
        == scenario["children"]
    )


def test_concurrent_handoffs_preserve_conflicting_frontiers(
    tmp_path, monkeypatch, offline_accounting
):
    from avo.cost_participation import (
        project_participation_facts,
        register_context,
        transition_context,
    )

    store, _ = production(tmp_path)
    participants = [
        register_context(store, host_descriptor(name))["participationId"]
        for name in ("source", "left", "right")
    ]
    barrier = Barrier(2)
    original_append = store.append_record

    def publish_together(kind, value):
        if value.get("kind") == "transition":
            barrier.wait(timeout=10)
        return original_append(kind, value)

    monkeypatch.setattr(store, "append_record", publish_together)
    requests = [
        transition_request(
            store,
            participants[0],
            target,
            operationId="fork-" + str(index),
            boundary={"kind": "event", "reference": "branch-" + str(index)},
        )
        for index, target in enumerate(participants[1:])
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda request: transition_context(store, request), requests)
        )
    projection = project_participation_facts(store.capture()["participations"])
    assert projection["conflicts"]
    state = next(
        item
        for item in projection["participations"]
        if item["participationId"] == participants[0]
    )
    assert state["conflicted"] is True
    assert set(state["frontier"]) == {result["factId"] for result in results}


def test_resume_accepts_only_measured_cumulative_baseline_of_same_source(
    tmp_path, offline_accounting
):
    from avo.cost_participation import register_context, transition_context

    store, _ = production(tmp_path)
    descriptor = host_descriptor("first")
    descriptor["scope"]["counterEpoch"] = "epoch-1"
    source = register_context(store, descriptor)["participationId"]
    semantics = deepcopy(profile()["semantics"])
    semantics["counter"] = "cumulative"
    frozen = store.append_record("profiles", profile(semantics=semantics))
    row = fact(
        "baseline",
        sourceInstanceId="first-source",
        sourceSessionId="first-session",
        measurementKind="cumulative",
        counterEpoch="epoch-1",
        sequence=1,
        tokens={"input": 100, "output": 10},
        semantics={},
        amounts=[],
    )
    metadata = evidence(
        row,
        participation_id=source,
        profile_id=frozen["profileId"],
        attribution={
            "status": "assigned",
            "basis": "exact synthetic counter baseline",
            "scope": descriptor["scope"],
        },
    )
    received = receipt(
        profile_id=frozen["profileId"],
        sourceInstanceId="first-source",
        sourceSessionId="first-session",
        counterEpoch="epoch-1",
        keys=[observation_key(row)],
        baseline={"status": "accepted", "reference": metadata["evidenceId"]},
    )
    incoming = packet(store, [row], evidence_rows=[metadata], receipts=[received])
    incoming["profileId"] = frozen["profileId"]
    store.ingest_packet(incoming, allow_synthetic=True)
    request = transition_request(
        store, source, source, kind="resume", baselineRef=metadata["evidenceId"]
    )
    accepted = transition_context(store, request)
    saved = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == accepted["factId"]
    )
    assert saved["baselineRef"] == metadata["evidenceId"]
    device = host_descriptor("new-device")
    device["scope"]["counterEpoch"] = "epoch-1"
    moved = transition_context(
        store,
        transition_request(
            store,
            source,
            declaration=device,
            operationId="device-resume",
            kind="resume",
            baselineRef=metadata["evidenceId"],
        ),
    )
    assert {item["code"] for item in moved["diagnostics"]} >= {
        "cost-transition-baseline-lineage-mismatch",
        "cost-transition-source-lineage-changed",
    }
    moved_fact = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == moved["factId"]
    )
    assert moved_fact["baselineRef"] is None


def _forked_context(store):
    from avo.cost_participation import build_participation_fact, register_context

    registered = register_context(store, host_descriptor("first"))
    base = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == registered["factId"]
    )
    variants = []
    for name in ("left", "right"):
        value = deepcopy(base)
        value.pop("factId")
        value.update(
            kind="revise", operationId="fork-" + name, predecessors=[base["factId"]]
        )
        value["agent"]["selectedModel"] = name
        variants.append(
            store.append_record("participations", build_participation_fact(value))
        )
    descriptor = host_descriptor("first")
    descriptor.update(
        operationId="reviewed-merge",
        participationId=registered["participationId"],
        predecessors=[item["factId"] for item in variants],
        reason="r" * 500,
    )
    descriptor["agent"]["selectedModel"] = "reviewed-current-hint"
    descriptor["provenance"]["digest"] = "a" * 64
    return descriptor


def test_context_merge_cli_preserves_reason_provenance_and_old_usage(
    tmp_path, capsys, offline_accounting
):
    from avo.cli import main
    from avo.cost_participation import project_participation_facts
    from avo.costs import summarize

    store, project_path = production(tmp_path)
    store.ingest([fact()])
    original_batches = {
        path: path.read_bytes() for path in store.path("batches").glob("*.json")
    }
    descriptor = _forked_context(store)
    supplied = store.raw_dir / "reviewed-context.json"
    supplied.write_text(json.dumps(descriptor), encoding="utf-8")
    argv = [
        "costs",
        "context",
        "--project",
        str(project_path),
        "--descriptor",
        str(supplied),
        "--json",
    ]
    assert main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    saved = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == result["factId"]
    )
    assert saved["reason"] == descriptor["reason"]
    assert saved["provenance"] == descriptor["provenance"]
    assert saved["scope"] == descriptor["scope"]
    assert (
        project_participation_facts(store.capture()["participations"])["conflicts"]
        == []
    )
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out)["replayed"] is True
    assert summarize(store)["tokens"]["total"] == 120
    assert {path: path.read_bytes() for path in original_batches} == original_batches
    assert store.capture()["bindings"] == []


def test_context_merge_rejects_stale_or_foreign_frontier_before_write(
    tmp_path, offline_accounting
):
    from avo.cost_participation import register_context

    store, _ = production(tmp_path)
    descriptor = _forked_context(store)
    register_context(store, descriptor)
    before = store.capture()["participations"]
    stale = deepcopy(descriptor)
    stale["operationId"] = "stale-merge"
    with pytest.raises(ValueError, match="frontier|predecessor"):
        register_context(store, stale)
    stale["predecessors"] = ["f" * 64]
    with pytest.raises(ValueError, match="frontier|predecessor"):
        register_context(store, stale)
    assert store.capture()["participations"] == before


@pytest.mark.parametrize("missing", ["participationId", "predecessors", "reason"])
def test_context_merge_requires_all_review_fields(missing):
    from avo.cost_participation import validate_context_descriptor

    descriptor = context_descriptor(
        participationId=PARTICIPATION_ID, predecessors=["a" * 64], reason="reviewed"
    )
    descriptor.pop(missing)
    with pytest.raises(ValueError):
        validate_context_descriptor(descriptor)


def _metadata_variants(tmp_path, *, three=False):
    store = registered_ledger(tmp_path)
    row = fact()
    variants = [
        evidence(row, nature="manual", modelBasis="unknown", acquisition=route)
        for route in (
            ("manual", "imported", "automatic") if three else ("manual", "imported")
        )
    ]
    for index, metadata in enumerate(variants):
        store.ingest_packet(
            packet(
                store, [row], evidence_rows=[metadata], operation_id=f"metadata-{index}"
            ),
            allow_synthetic=True,
        )
    return store, variants


def reconcile_request(store, old, new, **changes):
    value = reconciliation(store, old, new, **changes)
    value.pop("reconciliationId")
    value.pop("createdAt")
    return value


def test_reconcile_metadata_revision_and_withdraw_preserve_originals(
    tmp_path, offline_accounting
):
    from avo.cost_participation import reconcile_costs, resolve_evidence

    store, variants = _metadata_variants(tmp_path)
    original_bytes = {
        path: path.read_bytes() for path in store.path("batches").glob("*.json")
    }
    request = reconcile_request(store, *variants)
    result = reconcile_costs(store, request)
    assert reconcile_costs(store, request)["replayed"] is True
    assert resolve_evidence(variants, store.capture()["reconciliations"])[
        "selected"
    ] == [variants[1]]
    withdraw = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": "withdraw-1",
        "relation": "withdraw",
        "references": [{"kind": "decision", "id": result["reconciliationId"]}],
        "scope": request["scope"],
        "selectedRepresentation": None,
        "actor": "synthetic-reviewer",
        "reason": "withdraw prior metadata choice",
        "proofRefs": ["a" * 64],
        "supersedes": [result["reconciliationId"]],
    }
    reconcile_costs(store, withdraw)
    assert resolve_evidence(variants, store.capture()["reconciliations"])["conflicts"]
    assert len(store.capture()["reconciliations"]) == 2
    assert {path: path.read_bytes() for path in original_bytes} == original_bytes


def test_reconcile_competing_choices_need_explicit_supersession(
    tmp_path, offline_accounting
):
    from avo.cost_participation import reconcile_costs, resolve_evidence

    store, variants = _metadata_variants(tmp_path, three=True)
    decisions = [
        reconcile_costs(
            store,
            reconcile_request(
                store, variants[0], target, operationId="choice-" + str(index)
            ),
        )
        for index, target in enumerate(variants[1:])
    ]
    assert resolve_evidence(variants, store.capture()["reconciliations"])["conflicts"]
    request = reconcile_request(
        store,
        variants[0],
        variants[2],
        operationId="review-all-variants",
        references=[
            {"kind": "evidence", "id": item["evidenceId"]} for item in variants
        ],
        supersedes=[item["reconciliationId"] for item in decisions],
    )
    reconcile_costs(store, request)
    assert resolve_evidence(variants, store.capture()["reconciliations"])[
        "selected"
    ] == [variants[2]]


@pytest.mark.parametrize("bad", ["kind", "unknown", "foreign", "empty-proof"])
def test_reconcile_invalid_reference_never_publishes(tmp_path, offline_accounting, bad):
    from avo.cost_participation import reconcile_costs

    store, variants = _metadata_variants(tmp_path)
    request = reconcile_request(store, *variants)
    if bad == "kind":
        request["references"][0]["kind"] = "estimate"
    elif bad == "unknown":
        request["references"][0]["id"] = "f" * 64
    elif bad == "foreign":
        request["accountingVideoId"] = "00000000-0000-4000-8000-000000000099"
    else:
        request["proofRefs"] = []
    with pytest.raises(ValueError):
        reconcile_costs(store, request)
    assert store.capture()["reconciliations"] == []


def test_reconcile_changed_operation_payload_conflicts(tmp_path, offline_accounting):
    from avo.cost_participation import reconcile_costs

    store, variants = _metadata_variants(tmp_path)
    request = reconcile_request(store, *variants)
    reconcile_costs(store, request)
    with pytest.raises(ValueError, match="operation|replay"):
        reconcile_costs(store, {**request, "reason": "different reviewed choice"})
    assert len(store.capture()["reconciliations"]) == 1


def test_same_activity_cannot_replace_complete_tree_with_one_child(
    tmp_path, offline_accounting
):
    from avo.cost_participation import validate_reconciliation

    store = registered_ledger(tmp_path)
    children = [evidence(fact("child-" + str(index))) for index in range(2)]
    aggregate = evidence(
        fact("tree"),
        aggregateScope={
            "kind": "tree",
            "members": [item["key"] for item in children],
            "proofRefs": ["a" * 64],
        },
    )
    selected = {"kind": "evidence", "id": children[0]["evidenceId"]}
    decision = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": "false-partial-alias",
        "relation": "same-activity",
        "references": [{"kind": "evidence", "id": aggregate["evidenceId"]}, selected],
        "scope": aggregate["attribution"]["scope"],
        "selectedRepresentation": selected,
        "actor": "synthetic-reviewer",
        "reason": "a child alone is not the complete parent tree",
        "proofRefs": ["a" * 64],
        "supersedes": [],
        "createdAt": FIXED_TIME,
    }
    decision["reconciliationId"] = content_hash(decision)
    known = {item["evidenceId"]: item for item in [aggregate, *children]}
    with pytest.raises(ValueError, match="partial|tree|rollup"):
        validate_reconciliation(decision, known_refs=known)


def test_reconcile_metadata_cycle_is_rejected_before_append(
    tmp_path, offline_accounting
):
    from avo.cost_participation import reconcile_costs

    store, variants = _metadata_variants(tmp_path)
    reconcile_costs(store, reconcile_request(store, *variants))
    reverse = reconcile_request(
        store, variants[1], variants[0], operationId="cyclic-revision"
    )
    with pytest.raises(ValueError, match="cycle"):
        reconcile_costs(store, reverse)
    assert len(store.capture()["reconciliations"]) == 1


@pytest.mark.parametrize("known_model", [False, True])
def test_reconcile_served_model_upgrade_requires_frozen_source_proof(
    tmp_path, offline_accounting, known_model
):
    from avo.cost_participation import validate_reconciliation

    store = registered_ledger(tmp_path)
    row = fact(model="model-a" if known_model else None)
    old = evidence(row, nature="manual", modelBasis="selected-only")
    new = evidence(row, nature="manual", modelBasis="served")
    decision = reconciliation(store, old, new)
    known = {
        old["evidenceId"]: old,
        new["evidenceId"]: new,
        profile()["profileId"]: profile(),
        old["key"]["sourceDigest"]: {"key": old["key"], "observation": row},
    }
    if known_model:
        assert validate_reconciliation(decision, known_refs=known) == decision
    else:
        with pytest.raises(ValueError, match="served|qualified|model"):
            validate_reconciliation(decision, known_refs=known)


def test_reconcile_duplicate_allocation_requires_explicit_supersession(
    tmp_path, offline_accounting
):
    from avo.cost_participation import reconcile_costs, validate_reconciliation

    store, variants = _metadata_variants(tmp_path)
    metadata = variants[0]
    reference = {"kind": "evidence", "id": metadata["evidenceId"]}
    allocation = {
        "accountingVideoId": store.identity()["accountingVideoId"],
        "scope": metadata["attribution"]["scope"],
        "reference": reference,
    }
    request = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": "allocation-1",
        "relation": "allocation",
        "references": [reference],
        "scope": allocation["scope"],
        "selectedRepresentation": None,
        "allocations": [allocation],
        "actor": "synthetic-reviewer",
        "reason": "one exact activity allocation",
        "proofRefs": ["a" * 64],
        "supersedes": [],
    }
    first = reconcile_costs(store, request)
    saved = store.capture()["reconciliations"][0]
    assert validate_reconciliation(saved, known_refs=store.references()) == saved
    duplicate = {**deepcopy(request), "operationId": "allocation-2"}
    with pytest.raises(ValueError, match="allocation|supersede"):
        reconcile_costs(store, duplicate)
    duplicate["supersedes"] = [first["reconciliationId"]]
    assert reconcile_costs(store, duplicate)["status"] == "ok"


def test_concurrent_opposite_revisions_cannot_commit_cycle(
    tmp_path, monkeypatch, offline_accounting
):
    from avo.cost_participation import reconcile_costs

    store, variants = _metadata_variants(tmp_path)
    barrier = Barrier(2)
    append = store.append_record

    def start_together(kind, record):
        if kind == "reconciliations":
            barrier.wait(timeout=10)
        return append(kind, record)

    def reviewed(request):
        try:
            reconcile_costs(store, request)
            return "ok"
        except ValueError:
            return "conflict"

    monkeypatch.setattr(store, "append_record", start_together)
    requests = [
        reconcile_request(
            store, variants[0], variants[1], operationId="concurrent-left"
        ),
        reconcile_request(
            store, variants[1], variants[0], operationId="concurrent-right"
        ),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reviewed, requests))
    assert sorted(results) == ["conflict", "ok"]
    assert len(store.capture()["reconciliations"]) == 1
