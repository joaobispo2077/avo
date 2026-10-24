"""Explicit local usage imports; source contents are never instructions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from avo.cost_store import CostError, content_hash, read_json, validate

AGENTS = ("cursor", "claude", "codex", "windsurf", "cline", "gemini", "opencode")
FORMATS = {
    "codex": "documented exec JSONL",
    "opencode": "completed assistant-message export",
    "claude": "api_request event metadata",
    "gemini": "api_response event metadata",
}


def capabilities():
    return [
        {
            "agent": agent,
            "modes": ["normalized-import", "manual"]
            + (["local-import"] if agent in FORMATS else []),
            "sourceFormat": FORMATS.get(agent),
            "versions": ["documented-shape-v1"] if agent in FORMATS else [],
            "limitations": "Explicit session binding required; fields absent from evidence remain unknown. No account billing reconciliation.",
        }
        for agent in AGENTS
    ]


def _base(agent, session, request, occurred=None):
    return {
        "sourceInstanceId": agent,
        "sourceSessionId": session,
        "requestId": str(request),
        "agent": agent,
        "agentVersion": "documented-shape-v1",
        "model": None,
        "serviceProvider": None,
        "billingMode": "unknown",
        "serviceClass": "host-agent",
        "occurredAt": occurred,
        "tokens": {},
        "semantics": {},
        "amounts": [],
    }


def _codex(values, session):
    result = []
    for index, event in enumerate(values):
        if event.get("type") != "turn.completed":
            continue
        usage = event.get("usage") or {}
        row = _base(
            "codex",
            session,
            event.get("turn_id") or f"line-{index}",
            event.get("timestamp"),
        )
        row["tokens"] = {
            key: usage.get(native)
            for key, native in {
                "input": "input_tokens",
                "output": "output_tokens",
                "cacheRead": "cached_input_tokens",
                "reasoning": "reasoning_output_tokens",
            }.items()
        }
        row["semantics"] = {"cacheRead": "input", "reasoning": "output"}
        row["model"] = event.get("model")
        row["serviceProvider"] = event.get("provider")
        result.append(row)
    return result


def _opencode(value, session):
    result = []
    for message in value.get("messages", []):
        info = message.get("info", message)
        if info.get("role") != "assistant" or not info.get("time", {}).get("completed"):
            continue
        if info.get("sessionID") != session:
            continue
        occurred = datetime.fromtimestamp(
            info["time"]["completed"] / 1000, UTC
        ).isoformat()
        row = _base("opencode", session, info["id"], occurred)
        tokens = info.get("tokens") or {}
        row.update(model=info.get("modelID"), serviceProvider=info.get("providerID"))
        row["tokens"] = {k: tokens.get(k) for k in ("input", "output", "reasoning")}
        row["tokens"].update(
            cacheRead=tokens.get("cache", {}).get("read"),
            cacheWrite=tokens.get("cache", {}).get("write"),
        )
        row["semantics"] = {
            k: "disjoint" for k in ("reasoning", "cacheRead", "cacheWrite")
        }
        if info.get("cost") is not None:
            row["amounts"] = [
                {
                    "basis": "calculated-estimate",
                    "unit": "USD",
                    "amount": format(Decimal(str(info["cost"])), "f"),
                    "provenance": "OpenCode reported estimate",
                }
            ]
        result.append(row)
    return result


def _telemetry(values, agent, session):
    result = []
    for event in values:
        name = event.get("event.name") or event.get("name")
        expected = (
            "claude_code.api_request"
            if agent == "claude"
            else "gemini_cli.api_response"
        )
        if name != expected:
            continue
        data = event.get("attributes", event)
        if data.get("session.id", data.get("session_id")) != session:
            continue
        request = data.get("request_id") or data.get("client_request_id")
        if not request:
            raise CostError(
                "usage event lacks a stable request identity; use normalized import"
            )
        row = _base(agent, session, request, event.get("timestamp"))
        row.update(model=data.get("model"), serviceProvider=data.get("provider"))
        row["tokens"] = {
            key: data.get(native)
            for key, native in {
                "input": "input_tokens",
                "output": "output_tokens",
                "cacheRead": "cache_read_tokens",
                "cacheWrite": "cache_creation_tokens",
            }.items()
        }
        row["semantics"] = (
            {"cacheRead": "disjoint", "cacheWrite": "disjoint"}
            if agent == "claude"
            else {"cacheRead": "unknown", "cacheWrite": "unknown"}
        )
        row["amounts"] = _telemetry_amount(data)
        result.append(row)
    return result


def _telemetry_amount(data):
    from decimal import Decimal

    micros = data.get("cost_usd_micros")
    if micros is None:
        return []
    return [
        {
            "basis": "calculated-estimate",
            "unit": "USD",
            "amount": format(Decimal(str(micros)) / 1000000, "f"),
            "provenance": "agent telemetry estimate",
        }
    ]


def _read_events(path):
    if Path(path).stat().st_size > 32 * 1024 * 1024:
        raise CostError("usage input exceeds 32 MiB; supply a scoped export")
    raw = Path(path).read_text("utf-8")
    try:
        value = json.loads(raw)
        return value
    except ValueError:
        try:
            return [json.loads(line) for line in raw.splitlines() if line.strip()]
        except ValueError as exc:
            raise CostError(
                "incomplete or invalid usage export; retry after source flush"
            ) from exc


def import_file(path, source_format="normalized", *, session_id=None):
    if source_format not in {"normalized", *FORMATS}:
        raise CostError(
            "unsupported usage format; use normalized import or report-manual"
        )
    value = read_json(path) if source_format == "normalized" else _read_events(path)
    if source_format == "normalized":
        rows = value if isinstance(value, list) else value.get("observations")
    else:
        if not session_id:
            raise CostError("native import requires explicit source session identity")
        try:
            rows = _native(value, source_format, session_id)
        except (AttributeError, KeyError, TypeError, OverflowError) as exc:
            raise CostError(
                "invalid native usage metadata; use normalized import"
            ) from exc
    if not isinstance(rows, list) or len(rows) > 100000:
        raise CostError("invalid usage export or record limit exceeded")
    for row in rows:
        validate("observation", row)
    return rows


def _native(value, source_format, session_id):
    if source_format == "opencode":
        return _opencode(value, session_id)
    events = value if isinstance(value, list) else [value]
    if source_format == "codex":
        threads = {
            v.get("thread_id") for v in events if v.get("type") == "thread.started"
        }
        if threads != {session_id}:
            raise CostError("source thread differs from explicitly bound session")
        return _codex(events, session_id)
    return _telemetry(events, source_format, session_id)


def _active_bindings(store, binding_id):
    bindings = store.documents("bindings")
    superseded = {v.get("supersedesBindingId") for v in bindings}
    active = [v for v in bindings if v["bindingId"] not in superseded]
    if binding_id:
        active = [
            v
            for v in active
            if binding_id in {v["bindingId"], v.get("supersedesBindingId")}
        ]
        if not active:
            raise CostError("unknown source binding")
    return active


def _boundary_index(rows, boundary):
    index = next((i for i, r in enumerate(rows) if r["requestId"] == boundary), None)
    if index is None:
        raise CostError("source boundary unavailable; do not guess attribution")
    return index


def _binding_rows(binding):
    rows = import_file(
        binding["source"], binding["format"], session_id=binding["sourceSessionId"]
    )
    rows = [r for r in rows if r["sourceSessionId"] == binding["sourceSessionId"]]
    end = binding.get("endBoundary")
    if end:
        rows = rows[: _boundary_index(rows, end) + 1]
    if binding["boundary"] != "beginning":
        index = _boundary_index(rows, binding["boundary"])
        start = (
            index if rows[index].get("measurementKind") == "cumulative" else index + 1
        )
        rows = rows[start:]
    return [_binding_context(row, binding) for row in rows]


def _binding_context(row, binding):
    return {
        **row,
        **{
            key: binding[key]
            for key in ("runId", "phase")
            if not row.get(key) and binding.get(key)
        },
    }


def collect(store, binding_id=None):
    imported = 0
    diagnostics = []
    for binding in _active_bindings(store, binding_id):
        try:
            rows = _binding_rows(binding)
            # Binding identity is a local correlation; source identity remains stable across imports.
            if rows:
                imported += store.ingest(rows)["imported"]
        except (OSError, ValueError, KeyError, TypeError):
            diagnostics.append(
                {
                    "code": "source-unavailable-or-invalid",
                    "bindingId": binding["bindingId"],
                }
            )
    return {
        "status": "partial" if diagnostics else "ok",
        "imported": imported,
        "diagnostics": diagnostics,
    }


def source_fingerprint(path):
    return content_hash({"source": str(Path(path).resolve())})
