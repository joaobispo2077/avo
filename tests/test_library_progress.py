"""Busy library work still reports progress without inventing completion."""

from __future__ import annotations

import json
import threading
from copy import deepcopy

import pytest

from avo.library import progress
from avo.library.progress import Progress
from avo.library.rules import validate
from avo.library.store import LibraryStore


class Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value


class MemoryStore:
    def __init__(self, root):
        self.root = root
        self.cancel_ids = set()
        self.documents = []
        self.polled = threading.Event()
        self.poll_count = 0

    def cancelled(self, operation_id):
        self.poll_count += 1
        if self.poll_count >= 2:
            self.polled.set()
        return operation_id in self.cancel_ids

    def put(self, kind, document):
        validate(kind, document)
        self.documents.append((kind, deepcopy(document)))
        return {"id": f"report-{len(self.documents)}", "path": "fixture-report.json"}


def events(capsys):
    captured = capsys.readouterr()
    assert captured.out == ""
    return [
        json.loads(line.removeprefix("AVO_JSON "))
        for line in captured.err.splitlines()
        if line.startswith("AVO_JSON ")
    ]


def test_initial_activity_has_unknown_total_and_no_invented_eta(tmp_path, capsys):
    store = MemoryStore(tmp_path)
    with Progress(store, "scan", interval=0.02) as reporter:
        assert len(reporter.operation_id) == 32
        assert reporter.phase == "scan"
        first = events(capsys)[0]

    assert first["operationId"] == reporter.operation_id
    assert first["total"] is None
    assert first["percent"] is None
    assert first["etaSeconds"] is None
    assert first["estimateReason"]
    assert store.documents == []


def test_growing_totals_and_reuse_use_observations_not_savings(tmp_path, capsys):
    clock = Clock()
    store = MemoryStore(tmp_path)
    with Progress(store, "scan", clock=clock, interval=10) as reporter:
        clock.value += 2
        first = reporter.update(completed=1, total=5, current="recording-a", reused=1)
        clock.value += 1
        second = reporter.update(completed=2, total=10, failed=1)

    assert first["percent"] == 20
    assert first["etaSeconds"]["lower"] <= first["etaSeconds"]["upper"]
    assert first["estimateBasis"]
    assert second["total"] == 10 and second["completed"] == 2
    assert second["reused"] == 1 and second["failed"] == 1
    observed = events(capsys)
    assert [item["sequence"] for item in observed] == list(range(1, len(observed) + 1))
    assert all("savings" not in item and "tokensSaved" not in item for item in observed)


def test_inconsistent_total_never_displays_more_than_complete(tmp_path):
    with Progress(MemoryStore(tmp_path), "scan", emit=False) as reporter:
        event = reporter.update(completed=4, total=2)

    assert event["percent"] is None
    assert event["etaSeconds"] is None
    assert event["estimateReason"]


def test_independent_heartbeat_continues_while_owner_is_busy(tmp_path, capsys):
    store = MemoryStore(tmp_path)
    with Progress(store, "transcribe", interval=0.01):
        assert store.polled.wait(1), "Busy owner prevented independent heartbeat"

    observed = events(capsys)
    assert len(observed) >= 2
    assert all(item["completed"] == 0 for item in observed)
    assert store.documents == []


def test_cancellation_visible_without_marking_running_item_complete(tmp_path, capsys):
    store = MemoryStore(tmp_path)
    with Progress(store, "transcribe", interval=0.01) as reporter:
        reporter.update(current="recording-a", completed=0, total=5)
        store.cancel_ids.add(reporter.operation_id)
        assert reporter.cancelled is True
        store.polled.clear()
        assert store.polled.wait(1)

    observed = events(capsys)
    cancelled = [item for item in observed if item["cancelled"]]
    assert cancelled
    assert cancelled[-1]["status"] == "cancelling"
    assert cancelled[-1]["current"] == "recording-a"
    assert cancelled[-1]["completed"] == 0


def test_disk_footprint_observed_at_boundaries_not_heartbeat(tmp_path, monkeypatch):
    calls = []

    def observe(root):
        calls.append(root)
        return {
            "freeDiskBytes": 100,
            "libraryFootprintBytes": 25,
            "coverage": "fixture",
        }

    monkeypatch.setattr(progress, "_observe_resources", observe)
    store = MemoryStore(tmp_path)
    with Progress(store, "scan", interval=0.01) as reporter:
        assert store.polled.wait(1)
        assert len(calls) == 1
        reporter.update(completed=1, total=2)
        assert len(calls) == 1
        reporter.update(phase="proposal")
        assert len(calls) == 2
        reporter.finish()

    assert len(calls) == 3


@pytest.fixture
def finished_report(tmp_path):
    store = MemoryStore(tmp_path)
    clock = Clock()
    with Progress(store, "apply", emit=False, clock=clock) as reporter:
        reporter.update(completed=2, total=3, reused=1)
        clock.value += 4
        ref = reporter.finish(
            status="partial",
            estimates={"processingSeconds": {"lower": 3, "upper": 8}},
            counts={"processed": 2, "failed": 1, "createdBytes": 20, "movedBytes": 500},
            remaining=["recording-c"],
        )
        assert reporter.finish() == ref

    assert len(store.documents) == 1
    kind, report = store.documents[0]
    assert kind == "report"
    return report


def test_explicit_finish_preserves_estimates_actual_time_and_remaining(finished_report):
    assert finished_report["status"] == "partial"
    assert finished_report["elapsedSeconds"] == 4
    assert finished_report["estimates"]["processingSeconds"] == {"lower": 3, "upper": 8}
    assert finished_report["remaining"] == ["recording-c"]


def test_report_keeps_unknown_usage_and_separate_created_moved_bytes(finished_report):
    assert finished_report["resources"]["createdBytes"] == 20
    assert finished_report["resources"]["movedBytes"] == 500
    assert finished_report["usage"]["tokens"] is None
    assert finished_report["usage"]["amount"] is None
    assert finished_report["usage"]["coverage"] == "unavailable"


def test_context_exit_does_not_mask_errors_or_publish_success(tmp_path):
    store = MemoryStore(tmp_path)
    reporter = Progress(store, "apply", interval=0.01)
    with pytest.raises(RuntimeError, match="worker failed"):
        with reporter:
            raise RuntimeError("worker failed")

    assert not reporter._thread.is_alive()
    assert store.documents == []


def test_native_report_publication_does_not_rewrite_authority_head(tmp_path):
    store = LibraryStore(tmp_path, "example")
    store.initialize()
    before = store.head_path.read_bytes()
    with Progress(store, "scan", emit=False) as reporter:
        reporter.update(completed=1, total=1)
        ref = reporter.finish(counts={"processed": 1})

    report = store.get(ref)
    assert report["operationId"] == reporter.operation_id
    assert report["counts"]["processed"] == 1
    assert store.head_path.read_bytes() == before


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_invalid_interval_cannot_spin_or_disable_heartbeat(tmp_path, interval):
    with pytest.raises(ValueError):
        Progress(MemoryStore(tmp_path), "scan", interval=interval)


def test_admission_checks_cancellation_once_without_repeating_it_for_display(tmp_path):
    from avo.library.service import LibraryService

    store = MemoryStore(tmp_path)
    with Progress(store, "scan", emit=False) as reporter:
        service = object.__new__(LibraryService)
        service.progress = reporter
        before = store.poll_count
        service.activity(completed=1, total=10, current="recording-a")
        assert store.poll_count - before == 1
        store.cancel_ids.add(reporter.operation_id)
        with pytest.raises(ValueError, match="Cancellation acknowledged"):
            service.activity(completed=1, total=10, current="recording-b")
        assert reporter._current == "recording-a"
