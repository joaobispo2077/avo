"""Metadata-only usage capture for AVO-owned inference responses."""

import marshal
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from avo.avo_state import now_iso
from avo.cost_participation import evidence_id, legacy_evidence_id
from avo.cost_profiles import profile_id
from avo.cost_store import CostError, CostStore, _directory_lock, validate
from avo.timeline.contracts import content_hash


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


def _record_locked(store, response, endpoint, phase, request_id):
    host = urlsplit(endpoint).hostname
    view = store.capture()
    occurred_at = _response_time(
        response, request_id, store.identity()["accountingVideoId"], view
    )
    row = _normalize_response(
        response,
        host,
        store.identity()["accountingVideoId"],
        request_id,
        occurred_at,
        phase,
    )
    validate("observation", row)
    profile = _owned_profile()
    metadata = _service_evidence(row, profile["profileId"])
    operation = "avo.review:" + content_hash(
        {"key": metadata["key"], "profileId": profile["profileId"]}
    )
    previous = next(
        (batch for batch in view["batches"] if batch.get("operationId") == operation),
        None,
    )
    if previous is not None:
        result = _replay_response(store, previous, row, metadata)
        _audit_owned_upgrade(store, metadata, view)
        return result
    store.append_record("profiles", profile)
    packet = {
        "schemaVersion": "2.0.0",
        "operationId": operation,
        "accountingVideoId": store.identity()["accountingVideoId"],
        "profileId": profile["profileId"],
        "observations": [row],
        "evidence": [metadata],
        "receipts": [_service_receipt(row, metadata, view)],
    }
    result = store.ingest_packet(packet)
    _audit_owned_upgrade(store, metadata, view)
    return result


def _audit_owned_upgrade(store, metadata, view):
    key = metadata["key"]
    if not _legacy_owned_key(store, key, view):
        return
    old = legacy_evidence_id(key)
    operation = "avo.review:legacy-upgrade:" + content_hash(
        {"old": old, "new": metadata["evidenceId"]}
    )
    previous = next(
        (item for item in view["reconciliations"] if item["operationId"] == operation),
        None,
    )
    decision = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": operation,
        "relation": "revises-evidence",
        "references": [
            {"kind": "evidence", "id": identity}
            for identity in (old, metadata["evidenceId"])
        ],
        "scope": metadata["attribution"]["scope"],
        "selectedRepresentation": {"kind": "evidence", "id": metadata["evidenceId"]},
        "oldEvidenceId": old,
        "newEvidenceId": metadata["evidenceId"],
        "actor": "avo.review",
        "reason": "qualified owned response reobserved the exact legacy payload",
        "proofRefs": [
            key["sourceDigest"],
            metadata["profileId"],
            metadata["evidenceId"],
        ],
        "supersedes": [],
        "createdAt": previous["createdAt"] if previous else now_iso(),
    }
    store.append_record("reconciliations", decision)


def _legacy_owned_key(store, key, view):
    return any(
        key in (batch.get("observationKeys") or store.keys_for(batch["observations"]))
        for batch in view["batches"]
        if batch["schemaVersion"] == "1.0.0"
    )


def _normalize_response(response, host, session_id, request_id, occurred_at, phase):
    usage = _usage_mapping(response.get("usage"))
    prompt_details = _usage_mapping(usage.get("prompt_tokens_details"))
    completion_details = _usage_mapping(usage.get("completion_tokens_details"))
    local = host in {"localhost", "127.0.0.1", "::1"}
    return {
        "sourceInstanceId": "avo.review",
        "sourceSessionId": session_id,
        "requestId": request_id,
        "agent": "avo",
        "agentVersion": "1",
        "model": response.get("model"),
        "serviceProvider": host,
        "billingMode": "local" if local else "unknown",
        "serviceClass": "pipeline-service",
        "phase": phase,
        "occurredAt": occurred_at,
        "tokens": {
            "input": usage.get("prompt_tokens"),
            "output": usage.get("completion_tokens"),
            "cacheRead": prompt_details.get("cached_tokens"),
            "reasoning": completion_details.get("reasoning_tokens"),
        }
        | ({"total": usage["total_tokens"]} if "total_tokens" in usage else {}),
        "semantics": {"cacheRead": "input", "reasoning": "output"},
        "amounts": deepcopy(response.get("amounts", [])),
    }


def _usage_mapping(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CostError("invalid owned response usage metadata")
    return value


def _response_time(response, request_id, session_id, view):
    created = response.get("created")
    if type(created) in {int, float}:
        try:
            return (
                datetime.fromtimestamp(created, UTC).isoformat().replace("+00:00", "Z")
            )
        except (ValueError, OverflowError, OSError):
            pass
    for batch in sorted(view["batches"], key=lambda item: item.get("recordedOrder", 0)):
        for row in batch["observations"]:
            if (row["sourceInstanceId"], row["sourceSessionId"], row["requestId"]) == (
                "avo.review",
                session_id,
                request_id,
            ):
                return row["occurredAt"]
    return now_iso()


def _owned_profile():
    parser_digest = sha256(
        marshal.dumps(
            (
                _normalize_response.__code__,
                _usage_mapping.__code__,
                _response_time.__code__,
            )
        )
    ).hexdigest()
    fixtures = [
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "cached_tokens": 60,
            "reasoning_tokens": 5,
        },
        {"total_tokens": 120},
        {},
    ]
    fixture_digests = [content_hash(item) for item in fixtures]
    value = {
        "schemaVersion": "2.0.0",
        "agent": "avo",
        "surface": "owned-response",
        "versions": ["1"],
        "sourceFormat": "avo.review-chat-completions-v1",
        "parserVersion": "1",
        "parserDigest": parser_digest,
        "fixtureDigests": fixture_digests,
        "references": [
            {
                "url": "https://avo.local/schemas/avo.cost-observation.schema.json",
                "date": "2026-10-31",
            }
        ],
        "capability": "qualified",
        "semantics": {
            "counter": "request",
            "categoryOverlap": {"cacheRead": "input", "reasoning": "output"},
            "aggregateScope": "request",
            "revision": "immutable",
            "resume": "new-activities",
            "fork": "new-activities",
            "reset": "not-applicable",
            "finality": "source-flush",
        },
        "identityFields": ["id"],
        "allowedFields": [
            "id",
            "created",
            "model",
            "usage.prompt_tokens",
            "usage.completion_tokens",
            "usage.total_tokens",
            "usage.prompt_tokens_details.cached_tokens",
            "usage.completion_tokens_details.reasoning_tokens",
            "amounts",
        ],
        "limitations": [
            "AVO-owned responses only; this source does not measure the driving host agent.",
            "Without a native response id, replay identity across captures is unavailable.",
            "Missing native timestamps retain the first accepted capture time.",
            "Amounts require a typed extension and do not establish invoice reconciliation.",
        ],
        "qualification": {
            "kind": "native",
            "evidenceRefs": [
                content_hash({"normalizer": parser_digest, "fixtures": fixture_digests})
            ],
        },
    }
    value["profileId"] = profile_id(value)
    return value


def _service_evidence(row, profile_id):
    boundary = {"kind": "event", "reference": row["requestId"], "at": row["occurredAt"]}
    scope = {
        "runAliases": [],
        "beginning": boundary,
        "ending": boundary,
        "sourceInstanceId": row["sourceInstanceId"],
        "sourceSessionId": row["sourceSessionId"],
    }
    value = {
        "key": CostStore.keys_for([row])[0],
        "participationId": "pipeline-service:avo.review",
        "profileId": profile_id,
        "nature": "measured",
        "acquisition": "automatic",
        "sourceEventId": row["requestId"],
        "interval": {
            "sourceSessionId": row["sourceSessionId"],
            "counterEpoch": None,
            "start": boundary,
            "end": boundary,
        },
        "attribution": {
            "status": "assigned",
            "basis": "owned response in initialized video accounting",
            "scope": scope,
        },
        "modelBasis": "served" if row["model"] else "unknown",
        "aggregateScope": {"kind": "request", "members": [], "proofRefs": []},
    }
    value["evidenceId"] = evidence_id(value)
    return value


def _service_receipt(row, metadata, view):
    known_usage = any(value is not None for value in row["tokens"].values())
    reference = metadata["evidenceId"]
    value = {
        "profileId": metadata["profileId"],
        "bindingId": None,
        "sourceInstanceId": row["sourceInstanceId"],
        "sourceSessionId": row["sourceSessionId"],
        "predecessorReceiptId": _previous_service_receipt(
            row, metadata["profileId"], view
        ),
        "counterEpoch": None,
        "watermark": {"kind": "response", "value": row["requestId"]},
        "observationKeys": [metadata["key"]],
        "baseline": {"status": "not-applicable", "reference": None},
        "lifecycle": {"state": "closed", "reference": reference},
        "flush": {
            "status": "accepted" if known_usage else "missing",
            "reference": reference if known_usage else None,
        },
        "interval": metadata["interval"],
        "gaps": [] if known_usage else ["usage-unavailable"],
        "collectedAt": now_iso(),
    }
    value["receiptId"] = content_hash(value)
    return value


def _previous_service_receipt(row, profile_id, view):
    previous = None
    for batch in sorted(view["batches"], key=lambda item: item.get("recordedOrder", 0)):
        for receipt in batch.get("receipts", []):
            if (
                receipt["profileId"],
                receipt["sourceInstanceId"],
                receipt["sourceSessionId"],
                receipt["counterEpoch"],
            ) == (profile_id, row["sourceInstanceId"], row["sourceSessionId"], None):
                previous = receipt["receiptId"]
    return previous


def _replay_response(store, previous, row, metadata):
    if previous["observations"] != [row] or previous["evidence"] != [metadata]:
        raise CostError("owned response replay conflicts with accepted metadata")
    packet = {
        key: previous[key]
        for key in (
            "schemaVersion",
            "operationId",
            "accountingVideoId",
            "profileId",
            "observations",
            "evidence",
            "receipts",
        )
    }
    return store.ingest_packet(packet)


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
