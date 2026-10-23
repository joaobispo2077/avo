"""Closure reporting must match saved evidence and preserve cleanup gates."""

import json

import pytest

from avo.cost_closure import close_costs
from avo.cost_store import CostError, CostStore
from avo.costs import summarize
from test_costs import fact


def test_draft_and_final_share_known_totals(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact()])
    draft = close_costs(tmp_path, "draft")
    assert draft["tokens"] == summarize(store)["tokens"]
    receipt = tmp_path / "edit/cleanup/cleanup-result.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps({"status": "completed"}))
    final = close_costs(tmp_path, "final")
    assert final["tokens"] == draft["tokens"]
    assert final["lifecycle"] == "final"
    assert final["coverage"] == "partial"


def test_failed_cleanup_never_finalizes(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    with pytest.raises(CostError, match="cleanup"):
        close_costs(tmp_path, "final")


def test_portable_export_survives_source_removal(tmp_path):
    source = CostStore(tmp_path / "video")
    source.initialize("channel", "video")
    source.ingest([fact()])
    source.snapshot(summarize(source), "draft")
    destination = tmp_path / "archive"
    source.export(destination)
    archive = CostStore(destination, archive=True)
    assert summarize(source) == summarize(archive)
    snapshot = source.documents("snapshots")[0]
    assert archive.path(f"snapshots/{snapshot['snapshotId']}.json").is_file()


def test_cleanup_keeps_new_cost_files_after_inventory(tmp_path):
    from avo.project_inventory import PreservedSetResult, scan_delete_candidates

    cost = tmp_path / "edit/costs/batches/new.json"
    cost.parent.mkdir(parents=True)
    cost.write_text("{}")
    disposable = tmp_path / "edit/scratch.txt"
    disposable.write_text("scratch")
    preserved = PreservedSetResult([], None, [], [], [])
    paths, _ = scan_delete_candidates(tmp_path, preserved)
    assert cost not in paths
    assert disposable in paths


@pytest.mark.parametrize("stage", ["draft", "final"])
def test_wrap_export_and_report_use_identical_snapshot(tmp_path, monkeypatch, stage):
    from avo import avo_state, learndown_export, wrap

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    raw = tmp_path / "video"
    store = CostStore(raw)
    store.initialize("channel", "video")
    store.ingest([fact(), fact("switch", model="model-b", serviceProvider="service-b")])
    if stage == "final":
        receipt = raw / "edit/cleanup/cleanup-result.json"
        receipt.parent.mkdir()
        receipt.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "rawDir": str(raw),
                    "masterBasename": "master",
                    "deleted": [],
                    "freedBytes": 0,
                }
            )
        )
    payload = wrap.build_wrap_payload(
        {"rawDir": str(raw), "space": {}},
        session_id="s",
        provider="channel",
        master_basename="master",
        summary="Synthetic fixture",
        status=stage,
    )
    entry = learndown_export.export_provider_learndown(payload, root=tmp_path / "repo")
    exported = json.loads((entry / "learndown.json").read_text())
    assert exported["costs"] == payload["costs"]
    assert payload["costs"]["tokens"] == summarize(store)["tokens"]
    assert payload["costs"]["pendingTurn"] is True
    snapshot_id = payload["costs"]["snapshotId"]
    assert (entry / "costs/snapshots" / f"{snapshot_id}.json").is_file()
    assert (
        learndown_export.export_provider_learndown(payload, root=tmp_path / "repo")
        == entry
    )
    index = json.loads((entry.parent / "index.json").read_text())
    assert len(index["entries"]) == 1
