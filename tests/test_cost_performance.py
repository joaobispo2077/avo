"""A real local report over 100,000 synthetic observations."""

import os
import time
from uuid import uuid4

from avo.cost_store import CostStore
from avo.costs import summarize
from test_costs import fact


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
    started = time.perf_counter()
    report = summarize(store)
    elapsed = time.perf_counter() - started
    assert report["observationCount"] == 100000
    assert report["tokens"]["total"] == 12000000
    record_property("reportSeconds", elapsed)
    # Absolute latency is gated on the dedicated reference-machine run, not
    # coverage instrumentation or an arbitrary CI worker under parallel load.
    if os.environ.get("AVO_COST_BENCHMARK") == "1":
        assert elapsed < 5, f"100,000-observation report took {elapsed:.3f}s"
