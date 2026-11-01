"""Approved local batches cannot expand selection, limits or cache authority."""

from uuid import uuid4

import pytest

from avo.library import batch
from avo.library.rules import LibraryError
from avo.library.service import LibraryService
from avo.timeline.store import now_iso
from library_fixtures import install_provider, transcript_payload


@pytest.fixture
def library(tmp_path, monkeypatch):
    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    root.mkdir()
    for i in range(3):
        (root / f"xpto-{i}.mp4").write_bytes(f"raw {i}".encode())
    service = LibraryService(
        root, "example", probe=lambda _: {"durationSeconds": 20, "audio": True}
    )
    service.scan()
    monkeypatch.setattr(
        batch,
        "resolve_configuration",
        lambda *_: {
            "model": "small",
            "modelDir": "fixture-only",
            "device": "cpu",
            "computeType": "int8",
            "engineVersion": "fixture",
            "policyHash": "fixture-policy",
            "routingToken": "video-use+faster-whisper",
        },
    )
    return service


def request(service, *, route="local", limit=300):
    head = service.store.head()
    records = service.store.get(head["inventoryRef"])["recordings"]
    return {
        "schemaVersion": 1,
        "kind": "batchRequest",
        "requestId": uuid4().hex,
        "libraryId": head["libraryId"],
        "expectedHeadHash": head["headHash"],
        "recordingIds": [r["id"] for r in records],
        "route": route,
        "model": "small",
        "language": "en",
        "limits": {"workers": 1, "cpuThreads": 1, "maxProcessingSeconds": limit},
    }


def decision(service, packet):
    head = service.store.head()
    body = service.store.get(packet)
    return service.approve(
        {
            "schemaVersion": 1,
            "kind": "decision",
            "requestId": uuid4().hex,
            "libraryId": head["libraryId"],
            "expectedHeadHash": head["headHash"],
            "packetId": packet["id"],
            "packetHash": packet["sha256"],
            "approvedIds": [r["actionId"] for r in body["selected"]],
            "decision": "approved",
            "actor": "fixture",
            "creatorInstruction": "Transcribe exactly these test recordings",
            "createdAt": now_iso(),
        }
    )["decisionRef"]["id"]


class Runtime:
    calls = 0

    def __init__(self, **_kwargs):
        self.language = "en"

    def transcribe(self, path, _fingerprint):
        Runtime.calls += 1
        return transcript_payload(
            path, text="existing footage evidence", language="en", model="small"
        )


def test_prepare_never_dispatches_and_paid_is_unavailable(library):
    value = batch.prepare_batch(library, request(library))
    assert value["status"] == "prepared"
    assert value["estimates"]["tokens"] is None
    assert Runtime.calls == 0
    with pytest.raises(LibraryError) as error:
        batch.prepare_batch(library, request(library, route="paid"))
    assert error.value.code == "LIB_PAID_UNAVAILABLE"


def test_one_approval_only_selected_files_and_valid_resume_reuse(library):
    Runtime.calls = 0
    value = request(library)
    value["recordingIds"] = value["recordingIds"][:2]
    approval = decision(library, batch.prepare_batch(library, value)["packetRef"])
    result = batch.run_batch(
        library,
        approval,
        dispatcher=lambda service, op: batch.run_worker(
            service, op, runtime_factory=Runtime
        ),
    )
    assert result["status"] == "ok"
    assert Runtime.calls == 2
    assert result["summary"]["createdBytes"] > 0
    records = library.store.get(library.store.head()["inventoryRef"])["recordings"]
    assert sum(r["transcript"] is not None for r in records) == 2
    value = request(library)
    value["recordingIds"] = value["recordingIds"][:2]
    approval = decision(library, batch.prepare_batch(library, value)["packetRef"])
    again = batch.run_batch(
        library,
        approval,
        dispatcher=lambda service, op: batch.run_worker(
            service,
            op,
            runtime_factory=lambda **_: pytest.fail("all-cached batch loaded a model"),
        ),
    )
    assert again["summary"]["createdBytes"] == 0
    assert again["status"] == "ok"
    assert again["summary"]["reused"] == 2


def test_changed_source_after_approval_stops_batch(library):
    approval = decision(
        library, batch.prepare_batch(library, request(library))["packetRef"]
    )
    (library.root / "xpto-0.mp4").write_bytes(b"changed source")
    result = batch.run_batch(
        library,
        approval,
        dispatcher=lambda service, op: batch.run_worker(
            service, op, runtime_factory=Runtime
        ),
    )
    assert result["status"] == "partial"
    assert result["summary"]["failed"] == 1


def test_cancel_preserves_finished_item_and_resume_uses_valid_work(library):
    Runtime.calls = 0
    approval = decision(
        library, batch.prepare_batch(library, request(library))["packetRef"]
    )

    def dispatch(service, operation):
        return batch.run_worker(
            service,
            operation,
            runtime_factory=Runtime,
            after_item=lambda *_: service.store.cancel(operation),
        )

    first = batch.run_batch(library, approval, dispatcher=dispatch)
    assert first["status"] == "cancelled"
    assert Runtime.calls == 1
    resumed = batch.resume_batch(
        library,
        first["operationId"],
        dispatcher=lambda service, op: batch.run_worker(
            service, op, runtime_factory=Runtime
        ),
    )
    assert resumed["status"] == "ok"
    assert Runtime.calls == 3


def test_budget_and_bad_selection_fail_without_inference(library):
    value = request(library)
    value["recordingIds"].append("not-indexed")
    with pytest.raises(LibraryError):
        batch.prepare_batch(library, value)


def test_processing_allowance_is_cumulative_on_resume(library):
    Runtime.calls = 0
    approval = decision(
        library, batch.prepare_batch(library, request(library, limit=1))["packetRef"]
    )
    ticks = iter(i * 0.6 for i in range(100))
    dispatch = lambda service, op: batch.run_worker(
        service, op, runtime_factory=Runtime, clock=lambda: next(ticks)
    )
    first = batch.run_batch(library, approval, dispatcher=dispatch)
    assert first["status"] == "partial"
    calls = Runtime.calls
    again = batch.resume_batch(library, first["operationId"], dispatcher=dispatch)
    assert again["status"] == "partial" and Runtime.calls == calls


def test_corrupt_cached_payload_is_regenerated(library):
    Runtime.calls = 0
    approval = decision(
        library, batch.prepare_batch(library, request(library))["packetRef"]
    )
    dispatch = lambda service, op: batch.run_worker(
        service, op, runtime_factory=Runtime
    )
    assert batch.run_batch(library, approval, dispatcher=dispatch)["status"] == "ok"
    record = library.store.get(library.store.head()["inventoryRef"])["recordings"][0]
    library.store.path(record["transcript"]["path"]).write_text("{}")
    approval = decision(
        library, batch.prepare_batch(library, request(library))["packetRef"]
    )
    assert batch.run_batch(library, approval, dispatcher=dispatch)["status"] == "ok"
    assert Runtime.calls == 4


def test_hundred_recordings_cancel_resume_and_one_shared_runtime(library):
    from library_fixtures import make_library

    fixture = make_library(library.root / "hundred", count=100, playable=True)
    service = LibraryService(
        fixture.root, "example", probe=lambda _: {"durationSeconds": 1, "audio": True}
    )
    service.scan(recursive=True)
    created = []
    Runtime.calls = 0

    def factory(**kwargs):
        created.append(kwargs)
        return Runtime(**kwargs)

    approval = decision(
        service, batch.prepare_batch(service, request(service))["packetRef"]
    )
    steps = []

    def interrupted(svc, op):
        def after(record):
            steps.append(record["id"])
            if len(steps) == 50:
                svc.store.cancel(op)

        return batch.run_worker(svc, op, runtime_factory=factory, after_item=after)

    first = batch.run_batch(service, approval, dispatcher=interrupted)
    assert first["status"] == "cancelled" and Runtime.calls == 50 and len(created) == 1
    result = batch.resume_batch(
        service,
        first["operationId"],
        dispatcher=lambda svc, op: batch.run_worker(svc, op, runtime_factory=factory),
    )
    assert result["status"] == "ok" and Runtime.calls == 100 and len(created) == 2
    assert result["summary"]["completed"] == 100
    approval = decision(
        service, batch.prepare_batch(service, request(service))["packetRef"]
    )
    cached = batch.run_batch(
        service,
        approval,
        dispatcher=lambda svc, op: batch.run_worker(
            svc,
            op,
            runtime_factory=lambda **_: pytest.fail("cached batch loaded model"),
        ),
    )
    assert cached["summary"]["reused"] == 100
    value = request(library)
    value["limits"]["maxTemporaryBytes"] = 1
    with pytest.raises(LibraryError):
        batch.prepare_batch(library, value)
