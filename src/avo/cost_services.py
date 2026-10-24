"""Metadata-only usage capture for AVO-owned inference responses."""

from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from avo.avo_state import now_iso
from avo.cost_store import CostStore


def record_response(candidate, response, endpoint, *, phase="review"):
    """Only an already initialized ancestor project can own this usage."""
    for root in Path(candidate).resolve().parents:
        store = CostStore(root)
        if store.identity():
            return _record(store, response, endpoint, phase)
    return {"status": "not-recorded", "reason": "no declared video accounting identity"}


def _record(store, response, endpoint, phase):
    usage = response.get("usage") or {}
    host = urlsplit(endpoint).hostname
    local = host in {"localhost", "127.0.0.1", "::1"}
    row = {
        "sourceInstanceId": "avo.review",
        "sourceSessionId": store.identity()["accountingVideoId"],
        "requestId": str(response.get("id") or uuid4()),
        "agent": "avo",
        "agentVersion": "1",
        "model": response.get("model"),
        "serviceProvider": host,
        "billingMode": "local" if local else "unknown",
        "serviceClass": "pipeline-service",
        "phase": phase,
        "occurredAt": now_iso(),
        "tokens": {
            "input": usage.get("prompt_tokens"),
            "output": usage.get("completion_tokens"),
            "cacheRead": (usage.get("prompt_tokens_details") or {}).get(
                "cached_tokens"
            ),
            "reasoning": (usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens"
            ),
        },
        "semantics": {"cacheRead": "input", "reasoning": "output"},
        "amounts": [],
    }
    return store.ingest([row])


def try_record_response(candidate, response, endpoint, *, phase="review"):
    """Accounting errors are visible but must not change review results."""
    try:
        return record_response(candidate, response, endpoint, phase=phase)
    except (OSError, ValueError, TypeError):
        import warnings

        warnings.warn(
            "Review usage accounting unavailable; cost coverage is incomplete",
            RuntimeWarning,
            stacklevel=2,
        )
        return {"status": "unavailable"}
