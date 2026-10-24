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
