"""Regression proof for review-discovered counting and persistence risks."""

import json

from avo.cost_sources import collect
from avo.cost_store import CostStore
from avo.costs import summarize
from test_costs import fact


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
