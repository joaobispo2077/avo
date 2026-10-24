"""Service usage is distinct from host-agent usage and contains no content."""

import json

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
