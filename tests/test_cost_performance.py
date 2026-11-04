"""A real local report over 100,000 synthetic observations."""

import os
import platform
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from avo import costs
from avo.cost_store import CostError, CostStore
from avo.costs import summarize
from test_costs import fact


@pytest.mark.parametrize("case", ["correction", "conflict", "cumulative", "rollup"])
def test_legacy_projection_matches_general_with_current_context(
    tmp_path, monkeypatch, case
):
    from test_cost_continuity import registered_ledger

    store = registered_ledger(tmp_path)
    store.price(
        {
            "schemaVersion": "1.0.0",
            "model": "model-a",
            "serviceProvider": "service-a",
            "unit": "USD",
            "basis": "calculated-estimate",
            "effectiveAt": "2026-10-01T00:00:00Z",
            "provenance": "synthetic performance parity",
            "denominator": 1000,
            "rates": {"input": "1", "output": "2"},
        }
    )
    rows = [fact("first", amounts=[], tokens={"input": 100, "output": 20})]
    if case in {"correction", "conflict"}:
        rows.append(fact("first", tokens={"input": 150, "output": 20}))
    elif case == "cumulative":
        rows = [
            fact(
                str(index),
                measurementKind="cumulative",
                counterEpoch="e1",
                sequence=index,
                tokens={"input": index * 100, "output": index * 20},
                amounts=[],
            )
            for index in (1, 2, 3)
        ]
    else:
        rows[0]["inclusion"] = "rollup"
        rows.append(fact("child", parentRequestId="first", amounts=[]))
    rows.append(fact("owned-service", serviceClass="pipeline-service"))
    store.ingest(rows)
    if case == "correction":
        store.correct(
            store.observation_id(rows[0]),
            "select",
            "reviewer",
            "exact fixture",
            selected=store.digest(rows[0]),
        )
    closure = store.snapshot(
        summarize(store), "final", closure={"receiptHash": "synthetic-verified-cleanup"}
    )
    before = {p: p.read_bytes() for p in store.root.rglob("*.json")}
    view = store.capture()
    canonical_view = deepcopy(view)
    optimized = summarize(store, view=view)
    assert view == canonical_view
    monkeypatch.setattr(costs, "_only_legacy_evidence", lambda _: False)
    assert summarize(store, view=deepcopy(view)) == optimized
    assert optimized["previousClosureId"] == closure["snapshotId"]
    assert optimized["participations"]
    assert {p: p.read_bytes() for p in before} == before


def test_references_reuses_integrity_checked_batch_keys(tmp_path, monkeypatch):
    store = CostStore(tmp_path)
    store.initialize("channel", "key-reuse")
    store.ingest([fact()])
    view = store.capture()
    expected = store.references(view)

    def forbid_rebuilding(_):
        raise AssertionError("captured observation keys already exist")

    monkeypatch.setattr(store, "keys_for", forbid_rebuilding)
    assert store.references(view) == expected
    view["batches"][0]["observations"][0]["tokens"]["input"] += 1
    with pytest.raises(CostError, match="integrity"):
        store.references(view)
    with pytest.raises(CostError, match="integrity"):
        summarize(store, view=view)


def test_financial_view_reuses_exact_same_scope_totals(tmp_path):
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    store.price(
        {
            "schemaVersion": "1.0.0",
            "model": "model-a",
            "serviceProvider": "service-a",
            "unit": "USD",
            "basis": "calculated-estimate",
            "effectiveAt": "2026-10-01T00:00:00Z",
            "provenance": "synthetic frozen tariff",
            "denominator": 1000,
            "rates": {"input": "1", "output": "2", "cacheRead": "0.1"},
        }
    )
    rows = [fact("priced", amounts=[])]
    for request, unit, amount in (
        ("large", "USD", "123456789012345678901234567890.1234567890"),
        ("tiny", "USD", "0.0000000001"),
        ("credits", "credits", "3"),
    ):
        rows.append(
            fact(
                request,
                model=None,
                serviceProvider=None,
                amounts=[
                    {
                        "basis": "source-reported",
                        "unit": unit,
                        "amount": amount,
                        "provenance": "synthetic native amount without model",
                    }
                ],
            )
        )
    store.ingest_packet(
        packet(
            store,
            rows,
            evidence_rows=[
                evidence(row, modelBasis="served" if row["model"] else "unknown")
                for row in rows
            ],
        ),
        allow_synthetic=True,
    )
    report = summarize(store)
    expected = {
        ("calculated-estimate", "USD"): "0.086",
        ("source-reported", "USD"): "123456789012345678901234567890.1234567891",
        ("source-reported", "credits"): "3",
    }
    assert {(a["basis"], a["unit"]): a["amount"] for a in report["amounts"]} == expected
    views = report["financialViews"]
    assert {(a["basis"], a["unit"]): a["amount"] for a in views} == expected
    priced = next(view for view in views if view["basis"] == "calculated-estimate")
    assert priced["valuations"][0]["priceScheduleId"]
    assert sum(len(view["valuations"]) for view in views) == 4


def test_report_100000_observations(tmp_path, record_property):
    store = CostStore(tmp_path)
    identity = store.initialize("channel", "benchmark")
    # Trusted synthetic fixture publication avoids measuring import validation.
    for batch_index in range(20):
        batch = {
            "schemaVersion": "1.0.0",
            "batchId": str(uuid4()),
            "accountingVideoId": identity["accountingVideoId"],
            "createdAt": "2026-10-22T16:00:00Z",
            "recordedOrder": batch_index,
            "priceScheduleIds": [],
            "observations": [fact(str(batch_index * 5000 + i)) for i in range(5000)],
        }
        batch["observationKeys"] = store.keys_for(batch["observations"])
        batch["contentHash"] = store.digest(batch)
        store.publish(f"batches/{batch['batchId']}.json", batch)
    record_property("python", platform.python_version())
    record_property("processor", platform.processor())
    record_property("logicalCpuCount", os.cpu_count())
    record_property("batchCount", 20)
    record_property("observationCount", 100000)
    record_property(
        "fixtureBytes",
        sum(path.stat().st_size for path in store.path("batches").glob("*.json")),
    )
    started = time.perf_counter()
    report = summarize(store)
    elapsed = time.perf_counter() - started
    assert report["observationCount"] == 100000
    assert report["tokens"]["total"] == 12000000
    record_property("reportSeconds", elapsed)
    # Absolute latency is gated on the dedicated reference-machine run, not
    # coverage instrumentation or an arbitrary CI worker under parallel load.
    # User approved a 7 s budget for the complete v2 report on 2026-11-01.
    if os.environ.get("AVO_COST_BENCHMARK") == "1":
        assert elapsed < 7, f"100,000-observation report took {elapsed:.3f}s"


class _ReadMeter:
    def __init__(self, stream, reads):
        self.stream = stream
        self.reads = reads

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def read(self, size=-1):
        value = self.stream.read(size)
        self.reads["bytes"] += len(value)
        return value

    def readline(self, size=-1):
        value = self.stream.readline(size)
        self.reads["bytes"] += len(value)
        return value


def test_receipt_profile_capture_and_cold_warm_collection(
    tmp_path, monkeypatch, record_property
):
    from avo.cost_sources import COLLECTION_BYTE_LIMIT, collect_context
    from test_cost_sources import _automatic_context

    rows = [fact(str(index), agent="fixture-executor") for index in range(250)]
    store, context, source, _ = _automatic_context(
        tmp_path, rows, source_shape="normalized-jsonl"
    )
    original_open = Path.open
    reads = {"bytes": 0}

    def metered_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path == source and args and args[0] == "rb":
            return _ReadMeter(stream, reads)
        return stream

    monkeypatch.setattr(Path, "open", metered_open)
    started = time.perf_counter()
    assert collect_context(store, context)["imported"] == 250
    cold_seconds, cold_bytes = time.perf_counter() - started, reads["bytes"]
    assert cold_bytes <= COLLECTION_BYTE_LIMIT
    before = store.capture()
    reads["bytes"] = 0
    started = time.perf_counter()
    assert collect_context(store, context)["imported"] == 0
    warm_seconds, warm_bytes = time.perf_counter() - started, reads["bytes"]
    assert warm_bytes < cold_bytes // 4
    assert store.capture() == before
    started = time.perf_counter()
    capture = store.capture()
    capture_seconds = time.perf_counter() - started
    started = time.perf_counter()
    report = summarize(store)
    report_seconds = time.perf_counter() - started
    assert report["observationCount"] == 250
    assert report["tokens"]["total"] == 30000
    assert len(capture["profiles"]) == 1
    assert len(capture["batches"][0]["receipts"]) == 1
    record_property(
        "sourceFixture", "synthetic generic normalized JSONL, not vendor qualification"
    )
    record_property("sourceBytes", source.stat().st_size)
    record_property("coldSourceBytesRead", cold_bytes)
    record_property("warmSourceBytesRead", warm_bytes)
    record_property("coldCollectionSeconds", cold_seconds)
    record_property("warmCollectionSeconds", warm_seconds)
    record_property("receiptProfileCaptureSeconds", capture_seconds)
    record_property("receiptProfileReportSeconds", report_seconds)
