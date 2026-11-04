"""Service usage is distinct from host-agent usage and contains no content."""

import json

import pytest

from avo.cost_services import record_response
from avo.cost_store import CostStore
from avo.costs import summarize


def test_response_capture_ignores_choices_and_endpoint_credentials(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    candidate = tmp_path / "edit/proof.mp4"
    candidate.parent.mkdir(exist_ok=True)
    record_response(
        candidate,
        {
            "id": "req-1",
            "model": "actual-model",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [{"text": "PRIVATE"}],
        },
        "https://user:secret@example.invalid/v1?key=SECRET",
    )
    report = summarize(store)
    assert report["tokens"]["total"] == 120
    assert "pipeline-service" in report["breakdowns"]["serviceClass"]
    stored = json.dumps(store.documents("batches"))
    assert "PRIVATE" not in stored
    assert "SECRET" not in stored
    assert "secret" not in stored


def test_no_identity_is_not_guessed(tmp_path):
    result = record_response(
        tmp_path / "candidate.mp4", {"usage": {}}, "http://localhost:1234"
    )
    assert result["status"] == "not-recorded"


def _service_project(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    candidate = tmp_path / "edit/proof.mp4"
    candidate.parent.mkdir(exist_ok=True)
    return store, candidate


def test_owned_response_has_qualified_v2_service_evidence_without_a_host(tmp_path):
    store, candidate = _service_project(tmp_path)
    record_response(
        candidate,
        {
            "id": "owned-1",
            "model": "actual-model",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_tokens_details": {"cached_tokens": 60},
                "completion_tokens_details": {"reasoning_tokens": 5},
            },
        },
        "http://localhost:1234/v1",
    )
    batch = store.documents("batches")[0]
    assert batch["schemaVersion"] == "2.0.0"
    assert batch["observations"][0]["tokens"] == {
        "input": 100,
        "output": 20,
        "cacheRead": 60,
        "reasoning": 5,
    }
    assert batch["observations"][0]["semantics"] == {
        "cacheRead": "input",
        "reasoning": "output",
    }
    metadata = batch["evidence"][0]
    assert metadata["nature"] == "measured"
    assert metadata["acquisition"] == "automatic"
    assert metadata["participationId"] == "pipeline-service:avo.review"
    assert metadata["modelBasis"] == "served"
    assert batch["receipts"][0]["observationKeys"] == [metadata["key"]]
    assert store.documents("profiles")[0]["qualification"]["kind"] == "native"
    assert store.documents("profiles")[0]["versions"] == ["1"]
    assert store.documents("participations") == []
    assert summarize(store)["usageByNature"]["measured"]["total"] == 120


def test_owned_response_replay_reuses_timestamp_and_receipt(tmp_path, monkeypatch):
    from avo import cost_services

    store, candidate = _service_project(tmp_path)
    clock = {"now": "2026-10-31T12:00:00Z"}
    monkeypatch.setattr(cost_services, "now_iso", lambda: clock["now"])
    response = {
        "id": "owned-1",
        "model": "actual-model",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    first = record_response(candidate, response, "http://localhost:1234/v1")
    accepted = store.documents("batches")[0]
    clock["now"] = "2026-10-31T13:00:00Z"
    replay = record_response(candidate, response, "http://localhost:1234/v1")
    assert replay["batchId"] == first["batchId"]
    assert replay["imported"] == 0
    assert replay["replayed"] is True
    assert store.documents("batches") == [accepted]
    assert accepted["observations"][0]["occurredAt"] == "2026-10-31T12:00:00Z"
    assert summarize(store)["tokens"]["total"] == 120


def test_owned_response_changed_native_usage_is_an_auditable_variant(
    tmp_path, monkeypatch
):
    from avo import cost_services

    store, candidate = _service_project(tmp_path)
    clock = {"now": "2026-10-31T12:00:00Z"}
    monkeypatch.setattr(cost_services, "now_iso", lambda: clock["now"])
    response = {
        "id": "owned-1",
        "model": "actual-model",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    record_response(candidate, response, "http://localhost:1234/v1")
    clock["now"] = "2026-10-31T13:00:00Z"
    changed = {**response, "usage": {"prompt_tokens": 200, "completion_tokens": 20}}
    record_response(candidate, changed, "http://localhost:1234/v1")
    rows = [
        row for batch in store.documents("batches") for row in batch["observations"]
    ]
    assert len(rows) == 2
    assert {row["occurredAt"] for row in rows} == {"2026-10-31T12:00:00Z"}
    assert len({store.observation_id(row) for row in rows}) == 1
    report = summarize(store)
    assert report["observationCount"] == 0
    assert any(
        item["code"] == "conflicting-observation" for item in report["diagnostics"]
    )


def test_owned_response_native_timestamp_is_preserved(tmp_path, monkeypatch):
    from avo import cost_services

    store, candidate = _service_project(tmp_path)
    monkeypatch.setattr(cost_services, "now_iso", lambda: "2026-10-31T13:00:00Z")
    record_response(
        candidate,
        {
            "id": "owned-1",
            "created": 0,
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        },
        "http://localhost:1234/v1",
    )
    assert (
        store.documents("batches")[0]["observations"][0]["occurredAt"]
        == "1970-01-01T00:00:00Z"
    )


def test_owned_responses_without_native_ids_do_not_guess_identical_activity(tmp_path):
    store, candidate = _service_project(tmp_path)
    response = {
        "model": "actual-model",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    record_response(candidate, response, "http://localhost:1234/v1")
    record_response(candidate, response, "http://localhost:1234/v1")
    assert summarize(store)["tokens"]["total"] == 240


def test_owned_response_typed_amounts_survive_unknown_model_without_cost_guessing(
    tmp_path,
):
    store, candidate = _service_project(tmp_path)
    record_response(
        candidate,
        {
            "id": "owned-1",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost_usd": 999},
            "amounts": [
                {
                    "basis": "source-reported",
                    "unit": "USD",
                    "amount": "1",
                    "provenance": "typed source extension",
                }
            ],
        },
        "https://example.invalid/v1",
    )
    report = summarize(store)
    assert report["tokens"]["total"] == 120
    assert report["amounts"] == [
        {"basis": "source-reported", "unit": "USD", "amount": "1"}
    ]


def test_owned_response_replay_adds_missing_receipt_once_for_legacy_row(
    tmp_path, monkeypatch
):
    from avo import cost_services

    store, candidate = _service_project(tmp_path)
    stamp = "2026-10-31T12:00:00Z"
    monkeypatch.setattr(cost_services, "now_iso", lambda: "2026-10-31T13:00:00Z")
    store.ingest(
        [
            {
                "sourceInstanceId": "avo.review",
                "sourceSessionId": store.identity()["accountingVideoId"],
                "requestId": "owned-1",
                "agent": "avo",
                "agentVersion": "1",
                "model": "actual-model",
                "serviceProvider": "localhost",
                "billingMode": "local",
                "serviceClass": "pipeline-service",
                "phase": "review",
                "occurredAt": stamp,
                "tokens": {
                    "input": 100,
                    "output": 20,
                    "cacheRead": None,
                    "reasoning": None,
                },
                "semantics": {"cacheRead": "input", "reasoning": "output"},
                "amounts": [],
            }
        ]
    )
    response = {
        "id": "owned-1",
        "model": "actual-model",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    original = {
        path: path.read_bytes() for path in store.path("batches").glob("*.json")
    }
    frozen = store.snapshot(summarize(store), "draft")
    first = record_response(candidate, response, "http://localhost:1234/v1")
    second = record_response(candidate, response, "http://localhost:1234/v1")
    assert first["imported"] == second["imported"] == 0
    assert first["batchId"] == second["batchId"]
    batches = store.documents("batches")
    assert len(batches) == 2
    upgraded = next(batch for batch in batches if batch["schemaVersion"] == "2.0.0")
    assert upgraded["receipts"][0]["observationKeys"] == upgraded["observationKeys"]
    assert upgraded["observations"][0]["occurredAt"] == stamp
    assert len(store.observations()[0]) == 1
    decisions = store.documents("reconciliations")
    assert len(decisions) == 1
    assert decisions[0]["relation"] == "revises-evidence"
    assert decisions[0]["newEvidenceId"] == upgraded["evidence"][0]["evidenceId"]
    assert decisions[0]["proofRefs"]
    current = summarize(store)
    assert (
        current["tokens"]["total"]
        == current["usageByNature"]["measured"]["total"]
        == 120
    )
    assert {path: path.read_bytes() for path in original} == original
    assert (
        next(
            item
            for item in store.documents("snapshots")
            if item["snapshotId"] == frozen["snapshotId"]
        )
        == frozen
    )


def test_owned_response_without_usage_does_not_claim_flushed_measurement(tmp_path):
    store, candidate = _service_project(tmp_path)
    record_response(
        candidate,
        {"id": "owned-1", "model": "actual-model"},
        "http://localhost:1234/v1",
    )
    receipt = store.documents("batches")[0]["receipts"][0]
    assert receipt["lifecycle"]["state"] == "closed"
    assert receipt["flush"] == {"status": "missing", "reference": None}
    assert summarize(store)["tokens"]["total"] is None


def test_concurrent_first_owned_response_replay_has_one_capture_time(
    tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, current_thread

    from avo import cost_services

    store, candidate = _service_project(tmp_path)
    start = Barrier(2)
    monkeypatch.setattr(
        cost_services,
        "now_iso",
        lambda: (
            "2026-10-31T12:00:00Z"
            if current_thread().name.endswith("_0")
            else "2026-10-31T13:00:00Z"
        ),
    )
    response = {
        "id": "owned-1",
        "model": "actual-model",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }

    def capture():
        start.wait(timeout=10)
        return record_response(candidate, response, "http://localhost:1234/v1")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=30)
            for future in [pool.submit(capture), pool.submit(capture)]
        ]
    assert len({item["batchId"] for item in results}) == 1
    assert len(store.documents("batches")) == 1


@pytest.mark.parametrize(
    "response",
    [
        {
            "id": {"text": "PRIVATE"},
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        },
        {"id": "owned-1", "usage": [{"text": "PRIVATE"}]},
    ],
)
def test_malformed_owned_response_metadata_is_unavailable_without_private_data(
    tmp_path, response
):
    from avo.cost_services import try_record_response

    store, candidate = _service_project(tmp_path)
    with pytest.warns(RuntimeWarning, match="accounting unavailable"):
        result = try_record_response(candidate, response, "http://localhost:1234/v1")
    assert result == {"status": "unavailable"}
    assert store.documents("batches") == []
    assert store.documents("profiles") == []


def test_owned_response_retains_native_total_without_a_token_breakdown(tmp_path):
    store, candidate = _service_project(tmp_path)
    record_response(
        candidate,
        {"id": "owned-total", "usage": {"total_tokens": 120}},
        "https://example.invalid/v1",
    )
    assert store.documents("batches")[0]["observations"][0]["tokens"]["total"] == 120
    report = summarize(store)
    assert report["tokens"] == {"total": 120}
    assert report["usageByNature"]["measured"] == {"total": 120}
    assert report["amounts"] == []
