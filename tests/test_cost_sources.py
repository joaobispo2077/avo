"""Supported source capabilities and explicit, private-data-free imports."""

import json

import pytest

from avo.cost_sources import capabilities, collect, import_file
from avo.cost_store import CostError, CostStore
from test_costs import fact


def test_all_seven_agents_have_honest_fallback():
    values = capabilities()
    assert {v["agent"] for v in values} == {
        "claude",
        "codex",
        "gemini",
        "opencode",
        "cursor",
        "cline",
        "windsurf",
    }
    assert all("manual" in v["modes"] for v in values)


def test_codex_event_import_strips_content(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text(
        json.dumps({"type": "thread.started", "thread_id": "t1"})
        + "\n"
        + json.dumps({"type": "item.completed", "text": "PRIVATE"})
        + "\n"
        + json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 60,
                    "output_tokens": 20,
                },
            }
        )
        + "\n"
    )
    rows = import_file(source, "codex", session_id="t1")
    assert len(rows) == 1
    assert rows[0]["tokens"]["cacheRead"] == 60
    assert rows[0]["model"] is None
    assert "PRIVATE" not in json.dumps(rows)


def test_open_code_import_preserves_provider_switches(tmp_path):
    source = tmp_path / "source.json"
    messages = [
        {
            "info": {
                "role": "assistant",
                "id": f"m{i}",
                "sessionID": "s",
                "modelID": f"model-{i}",
                "providerID": f"service-{i}",
                "time": {"created": 1792684800000, "completed": 1792684801000},
                "tokens": {
                    "input": 100,
                    "output": 20,
                    "reasoning": 4,
                    "cache": {"read": 30, "write": 5},
                },
                "cost": 0.1,
            },
            "parts": [{"text": "PRIVATE"}],
        }
        for i in range(2)
    ]
    source.write_text(json.dumps({"messages": messages}))
    rows = import_file(source, "opencode", session_id="s")
    assert [r["serviceProvider"] for r in rows] == ["service-0", "service-1"]
    assert "PRIVATE" not in json.dumps(rows)


def test_collect_bound_source_skips_before_boundary(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    source = tmp_path / "usage.json"
    source.write_text(json.dumps([fact("before"), fact("start"), fact("after")]))
    binding = store.bind(
        source=source, agent="codex", session_id="session", boundary="start"
    )
    collect(store)
    assert {r["requestId"] for r in store.observations()[0]} == {"after"}
    assert binding["bindingId"]


def test_unavailable_source_does_not_erase_usage(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    source = tmp_path / "usage.json"
    source.write_text(json.dumps([fact()]))
    store.bind(source=source, agent="codex", session_id="session", boundary="beginning")
    collect(store)
    source.unlink()
    assert collect(store)["status"] == "partial"
    assert len(store.observations()[0]) == 1


def test_unknown_format_fails(tmp_path):
    with pytest.raises(CostError):
        import_file(tmp_path / "none", "private-unverified-format")


def test_opencode_tiny_charge_keeps_plain_decimal(tmp_path):
    source = tmp_path / "usage.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "info": {
                            "role": "assistant",
                            "id": "small",
                            "sessionID": "s",
                            "time": {"completed": 1792684801000},
                            "cost": 0.000001,
                        }
                    }
                ]
            }
        )
    )
    rows = import_file(source, "opencode", session_id="s")
    assert rows[0]["amounts"][0]["amount"] == "0.000001"
    store = CostStore(tmp_path / "video")
    store.initialize("channel", "tiny")
    store.ingest(rows)


@pytest.mark.parametrize("agent", ["claude", "gemini"])
def test_projected_telemetry_preserves_model_switch_and_strips_content(tmp_path, agent):
    name = "claude_code.api_request" if agent == "claude" else "gemini_cli.api_response"
    events = [
        {
            "name": name,
            "timestamp": "2026-10-22T16:00:00Z",
            "attributes": {
                "session.id": "s",
                "request_id": f"r{i}",
                "model": f"model-{i}",
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_tokens": 10,
                "cache_creation_tokens": 0,
                "cost_usd_micros": 1,
                "prompt": "PRIVATE",
            },
        }
        for i in range(2)
    ]
    source = tmp_path / "events.json"
    source.write_text(json.dumps(events))
    rows = import_file(source, agent, session_id="s")
    assert [r["model"] for r in rows] == ["model-0", "model-1"]
    assert all(r["serviceProvider"] is None for r in rows)
    assert "PRIVATE" not in json.dumps(rows)
    store = CostStore(tmp_path / "video")
    store.initialize("channel", "video")
    store.ingest(rows)
    from avo.costs import summarize

    assert summarize(store)["tokens"]["total"] == (260 if agent == "claude" else None)


def test_malformed_native_container_is_safe_error(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text('["PRIVATE"]')
    with pytest.raises(CostError, match="invalid"):
        import_file(source, "claude", session_id="s")
