"""Accounting invariants with synthetic usage, never paid inference."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from avo.cost_store import CostError, CostStore
from avo.costs import summarize


def fact(request="r1", **changes):
    value = {
        "sourceInstanceId": "synthetic",
        "sourceSessionId": "session",
        "requestId": request,
        "agent": "codex",
        "agentVersion": "fixture-1",
        "model": "model-a",
        "serviceProvider": "service-a",
        "billingMode": "api",
        "serviceClass": "host-agent",
        "occurredAt": "2026-10-22T16:00:00Z",
        "phase": "motion",
        "tokens": {"input": 100, "output": 20, "cacheRead": 60, "reasoning": 5},
        "semantics": {"cacheRead": "input", "reasoning": "output"},
        "amounts": [
            {
                "basis": "source-reported",
                "unit": "USD",
                "amount": "0.10",
                "provenance": "synthetic fixture",
            }
        ],
    }
    value.update(changes)
    return value


def test_switch_and_replay(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact(), fact("r2", model="model-b", serviceProvider="service-b")])
    store.ingest([fact()])
    report = summarize(store)
    assert report["tokens"]["total"] == 240
    assert report["amounts"][0]["amount"] == "0.20"
    assert len(report["breakdowns"]["model"]) == 2


def test_conflicting_observation_requires_explicit_correction(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    a = fact()
    b = fact(tokens={"input": 200, "output": 20})
    store.ingest([a])
    store.ingest([b])
    report = summarize(store)
    assert report["coverage"] == "partial"
    assert report["observationCount"] == 0
    store.correct(
        store.observation_id(a), "select", "human", "verified", selected=store.digest(a)
    )
    assert summarize(store)["tokens"]["total"] == 120


@pytest.mark.parametrize(
    "tokens", [{"input": -1}, {"output": True}, {"input": float("nan")}]
)
def test_bad_counts_rejected(tmp_path, tokens):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    with pytest.raises(CostError):
        store.ingest([fact(tokens=tokens)])
    assert store.observations()[0] == []


def test_private_fields_rejected(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    with pytest.raises(CostError, match="invalid"):
        store.ingest([fact(prompt="private conversation")])


def test_concurrent_replay_counts_once(tmp_path):
    store = CostStore(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = list(
            pool.map(lambda _: store.initialize("channel", "video"), range(4))
        )
        list(pool.map(lambda _: store.ingest([fact()]), range(8)))
    assert len({v["accountingVideoId"] for v in identities}) == 1
    assert summarize(store)["observationCount"] == 1


def test_snapshot_immutable_and_idempotent(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact()])
    first = store.snapshot(summarize(store), "draft")
    assert (
        store.snapshot(summarize(store), "draft")["snapshotId"] == first["snapshotId"]
    )
    store.ingest([fact("late")])
    second = store.snapshot(summarize(store), "amendment")
    assert first["tokens"]["total"] == 120
    assert second["tokens"]["total"] == 240


def test_unknown_price_and_units_do_not_turn_into_zero(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest(
        [
            fact(amounts=[]),
            fact(
                "r2",
                amounts=[
                    {
                        "basis": "manual",
                        "unit": "credits",
                        "amount": "3",
                        "provenance": "fixture",
                    }
                ],
            ),
        ]
    )
    report = summarize(store)
    assert report["coverage"] == "partial"
    assert report["amounts"] == [{"basis": "manual", "unit": "credits", "amount": "3"}]


def test_read_only_report_does_not_initialize(tmp_path):
    report = summarize(CostStore(tmp_path))
    assert report["coverage"] == "not-recorded"
    assert report["tokens"]["total"] is None
    assert not (tmp_path / "edit").exists()


def test_two_videos_are_isolated(tmp_path):
    a, b = CostStore(tmp_path / "a"), CostStore(tmp_path / "b")
    for s in (a, b):
        s.initialize("channel", "video")
    a.ingest([fact()])
    assert summarize(b)["observationCount"] == 0


def test_cumulative_baseline_and_reset(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    rows = [
        fact(
            "a",
            measurementKind="cumulative",
            counterEpoch="e1",
            sequence=1,
            tokens={"input": 100, "output": 10},
            amounts=[],
        ),
        fact(
            "b",
            measurementKind="cumulative",
            counterEpoch="e1",
            sequence=2,
            tokens={"input": 130, "output": 15},
            amounts=[],
        ),
    ]
    store.ingest(rows)
    assert summarize(store)["tokens"]["total"] == 35
    reset = deepcopy(rows[-1])
    reset.update(requestId="c", sequence=3, tokens={"input": 5, "output": 1})
    store.ingest([reset])
    assert summarize(store)["coverage"] == "partial"
    assert summarize(store)["tokens"]["total"] == 35


def test_frozen_price_and_revaluation(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    price = {
        "schemaVersion": "1.0.0",
        "model": "model-a",
        "serviceProvider": "service-a",
        "unit": "USD",
        "basis": "calculated-estimate",
        "effectiveAt": "2026-10-22T00:00:00Z",
        "provenance": "synthetic rates",
        "denominator": 1000,
        "rates": {"input": "1", "output": "2", "cacheRead": "0.1"},
    }
    store.price(price)
    store.ingest(
        [fact(amounts=[], semantics={"cacheRead": "input", "reasoning": "output"})]
    )
    report = summarize(store)
    assert report["amounts"][0]["amount"] == "0.086"


def test_measured_total_can_be_known_without_input_output_breakdown(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact(tokens={"total": 120}, semantics={})])
    assert summarize(store)["tokens"] == {"total": 120}
