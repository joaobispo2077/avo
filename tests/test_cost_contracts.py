"""Strict evidence boundaries and recovery behavior."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest

from avo.cost_sources import import_file
from avo.cost_store import CostError, CostStore, validate
from avo.costs import summarize
from test_cost_continuity import (
    FIXTURE_DIR,
    evidence,
    load_manifest,
    observation_key,
    packet,
    production,
    profile,
    receipt,
)
from test_costs import fact


@pytest.mark.parametrize(
    "agent", ["cursor", "claude", "codex", "windsurf", "cline", "gemini", "opencode"]
)
def test_each_agent_normalized_fallback(agent):
    fixture = Path(__file__).parent / "fixtures/costs/agents" / f"{agent}.json"
    rows = import_file(fixture)
    assert rows[0]["agent"] == agent
    assert rows[0]["agentVersion"] == "synthetic-manual-v1"


@pytest.mark.parametrize(
    "field,value",
    [
        ("agentVersion", None),
        ("occurredAt", "not-a-time"),
        ("tokens", {"output": float("inf")}),
        (
            "amounts",
            [
                {
                    "basis": "manual",
                    "unit": "USD",
                    "amount": "-1",
                    "provenance": "fixture",
                }
            ],
        ),
    ],
)
def test_invalid_field_rejected(field, value):
    with pytest.raises(CostError):
        validate("observation", fact(**{field: value}))


def test_path_escape_fails_closed(tmp_path):
    with pytest.raises(CostError):
        CostStore(tmp_path).publish("../../../outside.json", {})


def test_temp_and_lock_files_are_not_usage(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    directory = store.root / "batches"
    directory.mkdir()
    (directory / ".unfinished.tmp").write_text("PRIVATE partial payload")
    assert summarize(store)["observationCount"] == 0


def test_changed_hash_preserves_earlier_data_but_fails_report(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact()])
    path = next((store.root / "batches").glob("*.json"))
    value = json.loads(path.read_text())
    value["observations"][0]["tokens"]["input"] = 10000
    path.write_text(json.dumps(value))
    with pytest.raises(CostError, match="integrity"):
        summarize(store)


def test_snapshot_rejects_private_extension(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    report = summarize(store)
    report["prompt"] = "PRIVATE"
    with pytest.raises(CostError):
        store.snapshot(report, "draft")


def test_same_source_requires_explicit_close_before_another_video(
    tmp_path, monkeypatch
):
    from avo import avo_state

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    source = tmp_path / "source.json"
    source.write_text(json.dumps([fact("end")]))
    a, b = CostStore(tmp_path / "a"), CostStore(tmp_path / "b")
    for store in (a, b):
        store.initialize("channel", "video")
    binding = a.bind(
        source=source, agent="codex", session_id="session", boundary="beginning"
    )
    with pytest.raises(CostError, match="already bound"):
        b.bind(source=source, agent="codex", session_id="session", boundary="beginning")
    a.close_binding(binding["bindingId"], "end")
    assert b.bind(source=source, agent="codex", session_id="session", boundary="end")


def test_export_does_not_copy_forged_private_batch(tmp_path):
    store = CostStore(tmp_path / "video")
    store.initialize("channel", "video")
    store.ingest([fact()])
    path = next((store.root / "batches").glob("*.json"))
    value = json.loads(path.read_text())
    value["observations"][0]["prompt"] = "PRIVATE"
    path.write_text(json.dumps(value))
    with pytest.raises(CostError):
        store.export(tmp_path / "export")


def test_fractional_json_numbers_cannot_break_later_pricing():
    with pytest.raises(CostError, match="integers"):
        validate("observation", fact(tokens={"input": 100.0, "output": 20}))


def test_unknown_correction_is_rejected(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    with pytest.raises(CostError, match="unknown"):
        store.correct("absent", "exclude", "human", "fixture")


def test_concurrent_initialize_shares_one_identity(tmp_path, monkeypatch):
    store = CostStore(tmp_path)
    initial_reads = Barrier(2)
    original_identity = CostStore.identity

    def synchronized_identity(self):
        value = original_identity(self)
        if value is None:
            initial_reads.wait(timeout=10)
        return value

    monkeypatch.setattr(CostStore, "identity", synchronized_identity)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store.initialize, "channel", "video") for _ in range(2)]
        identities = [future.result(timeout=15) for future in futures]
    assert identities[0] == identities[1] == original_identity(store)
    assert len(list(store.root.glob("identity.json"))) == 1


def test_failed_batch_publish_keeps_accepted_evidence(tmp_path, monkeypatch):
    from avo import cost_store

    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact("accepted")])
    accepted_files = {
        path.name: path.read_bytes() for path in (store.root / "batches").glob("*.json")
    }
    accepted_report = summarize(store)

    def fail_replace(source, target):
        raise OSError("simulated interrupted publication")

    monkeypatch.setattr(cost_store.os, "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted publication"):
        store.ingest([fact("uncommitted")])
    assert {
        path.name: path.read_bytes() for path in (store.root / "batches").glob("*.json")
    } == accepted_files
    assert summarize(store) == accepted_report
    assert not list((store.root / "batches").glob("*.tmp"))
    assert not list((store.root / "batches").glob("*.lock"))


def test_identity_and_usage_survive_folder_rename(tmp_path):
    original = tmp_path / "original-video"
    renamed = tmp_path / "renamed-video"
    store = CostStore(original)
    identity = store.initialize("channel", "video")
    store.ingest([fact()])
    report = summarize(store)
    original.rename(renamed)
    moved = CostStore(renamed)
    assert moved.initialize("channel", "renamed-video") == identity
    assert summarize(moved) == report


def test_explicit_fork_retains_old_identity_and_evidence(tmp_path, monkeypatch):
    from avo import avo_state
    from avo.costs_cli import _fork

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    store = CostStore(tmp_path / "video")
    old_identity = store.initialize("channel", "original")
    store.ingest([fact()])
    old_report = summarize(store)
    new_identity = _fork(store, "forked")
    assert new_identity["accountingVideoId"] != old_identity["accountingVideoId"]
    assert new_identity["videoId"] == "forked"
    assert new_identity["provider"] == "channel"
    assert summarize(store)["observationCount"] == 0
    ancestor = CostStore(
        store.raw_dir / "edit/cost-ancestors" / old_identity["accountingVideoId"],
        archive=True,
    )
    assert ancestor.identity() == old_identity
    assert summarize(ancestor) == old_report


def _batch_v2(store, rows=None):
    rows = [fact()] if rows is None else rows
    value = packet(
        store, rows, receipts=[receipt(keys=[observation_key(row) for row in rows])]
    )
    value.update(
        batchId=CostStore.digest({"packet": value}),
        createdAt="2026-10-31T12:00:00Z",
        observationKeys=[observation_key(row) for row in rows],
        priceScheduleIds=[],
        profileIds=[value["profileId"]],
        recordedOrder=1,
    )
    value["contentHash"] = CostStore.digest(value)
    return value


def _snapshot_v2(store):
    frozen = json.loads(
        (FIXTURE_DIR / load_manifest()["legacyFixture"]).read_text("utf-8")
    )
    value = deepcopy(frozen["snapshot"])
    value.update(
        schemaVersion="2.0.0",
        accountingVideoId=store.identity()["accountingVideoId"],
        pendingTurn=None,
        pendingState="unknown",
        usageByNature={
            kind: {} for kind in ("measured", "manual", "legacy-unknown", "estimated")
        },
        participations=[],
        coverageBySource=[],
        selectedEvidenceIds=[],
        activeEstimateIds=[],
        unallocated={"tokens": {}, "amounts": []},
        conflicts={"tokens": {}, "amounts": []},
        previousClosureId=None,
    )
    for family in ("participations", "profiles", "estimates", "reconciliations"):
        value["membership"][family] = []
    value["snapshotId"] = CostStore.digest(
        {
            key: item
            for key, item in value.items()
            if key not in {"snapshotId", "recordedOrder"}
        }
    )
    return value


def test_v2_batch_dispatch_preserves_known_money_without_model(tmp_path):
    store, _ = production(tmp_path)
    row = fact(
        model=None,
        serviceProvider=None,
        amounts=[
            {
                "basis": "source-reported",
                "unit": "USD",
                "amount": "1",
                "provenance": "synthetic",
            }
        ],
    )
    value = _batch_v2(store, [row])
    assert validate("batch", value) is value
    assert value["observations"][0]["amounts"][0]["amount"] == "1"


def test_v2_batch_preserves_nanosecond_record_order(tmp_path):
    store, _ = production(tmp_path)
    value = _batch_v2(store)
    value["recordedOrder"] = 1793448000123456789
    value["contentHash"] = CostStore.digest(
        {key: item for key, item in value.items() if key != "contentHash"}
    )
    assert validate("batch", value) is value
    assert value["recordedOrder"] > 9007199254740991


def test_v2_packet_and_frozen_profile_validate(tmp_path):
    store, _ = production(tmp_path)
    row = fact()
    value = packet(store, [row], receipts=[receipt(keys=[observation_key(row)])])
    assert validate("packet", value) is value
    assert validate("profile", profile())["qualification"]["kind"] == "synthetic"


@pytest.mark.parametrize("location", ["packet", "evidence", "receipt", "profile"])
def test_v2_rejects_unrecognized_private_fields(tmp_path, location):
    store, _ = production(tmp_path)
    row = fact()
    value = packet(store, [row], receipts=[receipt(keys=[observation_key(row)])])
    if location == "profile":
        value = profile()
        value["prompt"] = "PRIVATE"
        kind = "profile"
    else:
        target = (
            value
            if location == "packet"
            else value[{"evidence": "evidence", "receipt": "receipts"}[location]][0]
        )
        target["prompt"] = "PRIVATE"
        kind = "packet"
    with pytest.raises(CostError):
        validate(kind, value)


@pytest.mark.parametrize("count", [-1, 9007199254740992, 1.5, 1.0, True])
def test_v2_nested_counts_require_bounded_python_integers(tmp_path, count):
    store, _ = production(tmp_path)
    value = _batch_v2(store, [fact(tokens={"input": count})])
    with pytest.raises(CostError):
        validate("batch", value)


@pytest.mark.parametrize(
    "pending,state",
    [(True, "open"), (True, "settling"), (False, "none"), (None, "unknown")],
)
def test_v2_snapshot_pending_mapping(tmp_path, pending, state):
    store, _ = production(tmp_path)
    value = _snapshot_v2(store)
    value.update(pendingTurn=pending, pendingState=state)
    value["snapshotId"] = CostStore.digest(
        {
            key: item
            for key, item in value.items()
            if key not in {"snapshotId", "recordedOrder"}
        }
    )
    assert validate("snapshot", value) is value


def test_v2_snapshot_rejects_contradictory_pending_state(tmp_path):
    store, _ = production(tmp_path)
    value = _snapshot_v2(store)
    value["pendingTurn"] = False
    with pytest.raises(CostError):
        validate("snapshot", value)


@pytest.mark.parametrize("version", ["1.1.0", "2.1.0", "3.0.0", None])
def test_unknown_batch_versions_are_rejected(tmp_path, version):
    store, _ = production(tmp_path)
    value = _batch_v2(store)
    value["schemaVersion"] = version
    with pytest.raises(CostError):
        validate("batch", value)


def test_v2_evidence_ids_and_profile_references_are_strict(tmp_path):
    store, _ = production(tmp_path)
    value = packet(store, [fact()], receipts=[receipt()])
    value["evidence"][0]["profileId"] = "not-a-profile-digest"
    with pytest.raises(CostError):
        validate("packet", value)
    item = evidence(fact())
    item["key"]["sourceDigest"] = "not-an-observation-digest"
    with pytest.raises(CostError):
        validate("evidence", item)


def test_exact_v1_snapshot_payload_and_hash_survive_validation(tmp_path):
    store, _ = production(tmp_path)
    frozen = json.loads(
        (FIXTURE_DIR / load_manifest()["legacyFixture"]).read_text("utf-8")
    )
    snapshot = frozen["snapshot"]
    path = store.root / "snapshots" / f"{snapshot['snapshotId']}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
    before = path.read_bytes()
    assert snapshot["schemaVersion"] == "1.0.0"
    assert type(snapshot["pendingTurn"]) is bool
    assert validate("snapshot", snapshot) == snapshot
    assert store.documents("snapshots") == [snapshot]
    assert path.read_bytes() == before


def test_v2_bundled_schema_references_need_no_network(tmp_path):
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource

    from avo.paths import schema_path

    def no_remote_schema(uri):
        pytest.fail(f"cost schemas must resolve from bundled resources: {uri}")

    registry = Registry(retrieve=no_remote_schema)
    documents = {}
    for path in schema_path("avo.cost-evidence.schema.json").parent.glob(
        "avo.cost-*.schema.json"
    ):
        document = json.loads(path.read_text("utf-8"))
        Draft202012Validator.check_schema(document)
        documents[path.name] = document
        registry = registry.with_resource(
            document["$id"], Resource.from_contents(document)
        )

    store, _ = production(tmp_path)
    for name, value in (
        ("avo.cost-batch.v2.schema.json", _batch_v2(store)),
        ("avo.cost-snapshot.v2.schema.json", _snapshot_v2(store)),
    ):
        Draft202012Validator(
            documents[name], registry=registry, format_checker=FormatChecker()
        ).validate(value)
