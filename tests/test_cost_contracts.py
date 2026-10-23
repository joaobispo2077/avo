"""Strict evidence boundaries and recovery behavior."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from avo.cost_sources import import_file
from avo.cost_store import CostError, CostStore, validate
from avo.costs import summarize
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
