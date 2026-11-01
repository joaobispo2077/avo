"""Historical valuation and portable provider history without original logs."""

from avo import avo_state, cost_history
from avo.cost_store import CostStore
from avo.costs import summarize
from test_costs import fact


def test_history_survives_offline_footage(tmp_path, monkeypatch):
    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cost_history, "providers_dir", lambda: tmp_path / "providers")
    store = CostStore(tmp_path / "video")
    store.initialize("channel", "video")
    store.ingest([fact()])
    store.snapshot(summarize(store), "draft")
    store.export(tmp_path / "providers/channel/learndowns/entry/costs")
    store.raw_dir.rename(tmp_path / "offline-video")
    videos = cost_history.history()["videos"]
    assert len(videos) == 1
    assert videos[0]["tokens"]["total"] == 120


def test_late_usage_creates_amendment_and_no_duplicate_video(tmp_path, monkeypatch):
    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cost_history, "providers_dir", lambda: tmp_path / "providers")
    store = CostStore(tmp_path / "video")
    store.initialize("channel", "video")
    store.ingest([fact()])
    final = store.snapshot(
        summarize(store), "final", closure={"receiptHash": "synthetic"}
    )
    cost_history.remember(store)
    store.ingest([fact("late")])
    videos = cost_history.history()["videos"]
    assert len(videos) == 1
    assert videos[0]["lifecycle"] == "amendment"
    assert videos[0]["tokens"]["total"] == 240
    assert final["tokens"]["total"] == 120


def test_trends_need_two_matching_valuations():
    one = {
        "lifecycle": "final",
        "coverage": "partial",
        "amounts": [{"basis": "manual", "unit": "USD", "amount": "1"}],
    }
    assert cost_history.trends({"videos": [one]})[0]["meanPerVideo"] is None
    result = cost_history.trends({"videos": [one, one]})
    assert result[0]["sampleSize"] == 2
    assert result[0]["meanPerVideo"] == "1"


def test_phase_filter_keeps_unknowns_out_of_named_phase(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact(), fact("unknown", phase=None)])
    assert summarize(store)["tokens"]["total"] == 240
    assert summarize(store, phase="motion")["tokens"]["total"] == 120


def test_old_learndown_is_unknown_not_zero(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cost_history, "providers_dir", lambda: tmp_path / "providers")
    entry = tmp_path / "providers/channel/learndowns/old/learndown.json"
    entry.parent.mkdir(parents=True)
    entry.write_text(
        json.dumps(
            {
                "provider": "channel",
                "entryId": "old",
                "status": "final",
                "masterBasename": "old-master",
            }
        )
    )
    videos = cost_history.history()["videos"]
    assert len(videos) == 1
    assert videos[0]["coverage"] == "not-recorded"
    assert videos[0]["tokens"]["total"] is None


def test_trends_separate_different_service_scopes():
    common = {
        "lifecycle": "final",
        "coverage": "partial",
        "amounts": [{"basis": "manual", "unit": "USD", "amount": "1"}],
    }
    videos = [
        {**common, "breakdowns": {"serviceClass": {kind: {}}}}
        for kind in ("host-agent", "pipeline-service")
    ]
    result = cost_history.trends({"videos": videos})
    assert len(result) == 2
    assert all(c["sampleSize"] == 1 and c["meanPerVideo"] is None for c in result)


def _bound_source(tmp_path):
    import json

    store = CostStore(tmp_path / "video")
    store.initialize("channel", "video")
    source = tmp_path / "usage.json"
    source.write_text(json.dumps([fact("start"), fact("end")]), encoding="utf-8")
    args = {
        "source": source,
        "agent": "codex",
        "session_id": "session",
        "boundary": "start",
    }
    return store, source, args, store.bind(**args)


def test_binding_replay_keeps_original_grant_when_source_is_offline(tmp_path):
    store, source, args, original = _bound_source(tmp_path)
    assert store.bind(**args) == original
    source.unlink()
    assert store.bind(**args) == original
    assert len(store.documents("bindings")) == 1


def test_closed_binding_resolves_canonical_identity_and_close_replays(tmp_path):
    store, _, _, original = _bound_source(tmp_path)
    closed = store.close_binding(original["bindingId"], "end")
    resolved = store.resolve_binding(closed["bindingId"])
    assert resolved["bindingId"] == original["bindingId"]
    assert resolved["endBoundary"] == "end"
    assert store.resolve_binding(original["bindingId"]) == resolved
    assert store.close_binding(original["bindingId"], "end") == closed
    assert len(store.documents("bindings")) == 2


def test_binding_resolution_rejects_divergent_scope_changes(tmp_path):
    from uuid import uuid4

    import pytest

    from avo.cost_store import CostError

    store, _, _, original = _bound_source(tmp_path)
    store.close_binding(original["bindingId"], "end")
    other = {
        **original,
        "bindingId": str(uuid4()),
        "supersedesBindingId": original["bindingId"],
        "endBoundary": "other-end",
    }
    store.publish(f"bindings/{other['bindingId']}.json", other)
    with pytest.raises(CostError):
        store.resolve_binding(original["bindingId"])


def test_exact_v1_snapshot_lookup_never_rewrites_legacy_payload(tmp_path):
    import json

    from test_cost_continuity import FIXTURE_DIR, load_manifest

    manifest = load_manifest()
    frozen = json.loads((FIXTURE_DIR / manifest["legacyFixture"]).read_text("utf-8"))
    store = CostStore(tmp_path / "archive", archive=True)
    store.publish("identity.json", frozen["identity"])
    store.publish("batches/" + frozen["batch"]["batchId"] + ".json", frozen["batch"])
    target = "snapshots/" + frozen["snapshot"]["snapshotId"] + ".json"
    store.publish(target, frozen["snapshot"])
    before = {path: path.read_bytes() for path in store.root.rglob("*.json")}
    assert store.read_snapshot(frozen["snapshot"]["snapshotId"]) == frozen["snapshot"]
    assert summarize(store)["tokens"]["total"] == manifest["legacy"]["serviceTokens"]
    assert {path: path.read_bytes() for path in store.root.rglob("*.json")} == before


def test_stale_raw_capture_dominates_older_closed_export_without_writes(
    tmp_path, monkeypatch
):
    import pytest

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cost_history, "providers_dir", lambda: tmp_path / "providers")
    store = CostStore(tmp_path / "video")
    store.initialize("channel", "video")
    store.ingest([fact()])
    original = store.snapshot(
        summarize(store), "final", closure={"receiptHash": "synthetic-verified-cleanup"}
    )
    archive = tmp_path / "providers/channel/learndowns/older/costs"
    store.export(archive)
    cost_history.remember(store)

    def interrupted_amendment():
        raise OSError("synthetic accepted late usage before closure repair")

    with monkeypatch.context() as interrupted:
        interrupted.setattr(store, "amend_if_closed", interrupted_amendment)
        with pytest.raises(OSError):
            store.ingest([fact("late")])
    before = {
        path: path.read_bytes()
        for root in (store.root, archive)
        for path in root.rglob("*.json")
    }
    result = cost_history.history(store=store)
    assert len(result["videos"]) == 1
    current = result["videos"][0]
    assert current["tokens"]["total"] == 240
    assert current["membership"] == summarize(store)["membership"]
    assert "closure-stale" in str(current["diagnostics"]) + str(result["diagnostics"])
    assert {
        path: path.read_bytes()
        for root in (store.root, archive)
        for path in root.rglob("*.json")
    } == before
    assert store.documents("snapshots") == [original]
