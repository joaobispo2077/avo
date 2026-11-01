"""Explicit local usage imports; source contents are never instructions."""

from __future__ import annotations

import json
from copy import deepcopy
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
COLLECTION_BYTE_LIMIT = 8 * 1024 * 1024
COLLECTION_RECORD_LIMIT = 10000
COLLECTION_RECORD_BYTE_LIMIT = 1024 * 1024
COLLECTION_PACKET_BYTE_LIMIT = 32 * 1024 * 1024


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


def _validated_import_rows(rows):
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


def _accepted_context(view, context, identity):
    if not isinstance(context, dict):
        raise CostError("accepted cost context unavailable")
    facts = [
        item
        for item in view["participations"]
        if item["factId"] == context.get("factId")
    ]
    if (
        len(facts) != 1
        or context.get("accountingVideoId") != identity["accountingVideoId"]
        or context.get("participationId") != facts[0]["participationId"]
    ):
        raise CostError("accepted cost context unavailable")
    return facts[0]


def _attached_context(store, binding):
    view = store.capture()
    canonical = store.resolve_binding(binding["bindingId"], bindings=view["bindings"])
    superseded = {
        parent for f in view["participations"] for parent in f["predecessors"]
    }
    owners = []
    associated = False
    for fact in view["participations"]:
        attachment = fact.get("sourceAttachment")
        if not attachment:
            continue
        resolved = store.resolve_binding(
            attachment["bindingId"], bindings=view["bindings"]
        )
        if resolved["bindingId"] == canonical["bindingId"]:
            associated = True
            if fact["factId"] not in superseded:
                owners.append(fact)
    if len(owners) > 1:
        raise CostError("source binding has ambiguous context ownership")
    if not owners:
        if associated:
            raise CostError("source binding has no current explicit context attachment")
        return None
    return {
        "factId": owners[0]["factId"],
        "accountingVideoId": owners[0]["accountingVideoId"],
        "participationId": owners[0]["participationId"],
    }


def _context_source(store, view, fact):
    from avo.cost_participation import _binding_matches
    from avo.cost_profiles import resolve_profile

    attachment = fact["sourceAttachment"]
    binding = store.resolve_binding(attachment["bindingId"], bindings=view["bindings"])
    profile = next(
        (
            item
            for item in view["profiles"]
            if item["profileId"] == attachment["profileId"]
        ),
        None,
    )
    agent = fact["agent"]
    if profile is None:
        raise CostError("cost context source is not compatible with request collection")
    binding_scope = (binding["agent"], binding["format"])
    if binding_scope != (agent["family"], "normalized") or not _binding_matches(
        fact, binding
    ):
        raise CostError("cost context source is not compatible with request collection")
    selected = resolve_profile(
        [profile],
        agent=agent["family"],
        surface=agent["surface"],
        version=agent["version"],
        source_format=profile["sourceFormat"],
    )
    if (
        not _supported_collection(profile)
        or selected is None
        or "requestId" not in profile["identityFields"]
    ):
        raise CostError("cost context source is not qualified for collection")
    return binding, selected


def _supported_collection(profile):
    semantics = profile["semantics"]
    return (
        profile["sourceFormat"],
        semantics["counter"],
        semantics["aggregateScope"],
    ) in {
        ("normalized", "request", "request"),
        ("normalized-jsonl", "request", "request"),
        ("normalized-jsonl", "cumulative", "thread"),
    }


def _context_evidence(row, key, fact, profile, temporal):
    from avo.cost_participation import evidence_id

    boundary = {"kind": "event", "reference": row["requestId"]}
    value = {
        "key": key,
        "participationId": fact["participationId"],
        "participationFactId": fact["factId"],
        "profileId": profile["profileId"],
        "nature": "measured",
        "acquisition": "automatic",
        "sourceEventId": row["requestId"],
        "interval": {
            "sourceSessionId": row["sourceSessionId"],
            "counterEpoch": row.get("counterEpoch"),
            "start": {"kind": "event", "reference": temporal["start"]},
            "end": deepcopy(boundary),
        },
        "attribution": {
            "status": "unallocated" if temporal["gaps"] else "assigned",
            "basis": "authorized exact context binding",
            "scope": _row_scope(row, fact, boundary),
        },
        "modelBasis": "served" if row.get("model") else "unknown",
        "aggregateScope": {
            "kind": profile["semantics"]["aggregateScope"],
            "members": [],
            "proofRefs": [],
        },
    }
    value["evidenceId"] = evidence_id(value)
    return value


def _row_scope(row, fact, boundary):
    alias = row.get("runId")
    return {
        "runAliases": [alias] if alias in fact["scope"]["runAliases"] else [],
        "sourceInstanceId": row["sourceInstanceId"],
        "sourceSessionId": row["sourceSessionId"],
        "counterEpoch": row.get("counterEpoch"),
        "beginning": deepcopy(boundary),
        "ending": deepcopy(boundary),
    }


def _source_receipts(view, binding, profile):
    return [
        item
        for batch in view["batches"]
        for item in batch.get("receipts", [])
        if item["bindingId"] == binding["bindingId"]
        and item["profileId"] == profile["profileId"]
    ]


def _lineage(row):
    return (row["sourceInstanceId"], row["sourceSessionId"], row.get("counterEpoch"))


def _receipt_frontier(receipts, lineage):
    selected = {r["receiptId"]: r for r in receipts if _lineage(r) == lineage}
    parents = {r["predecessorReceiptId"] for r in selected.values()}
    heads = set(selected) - parents
    if len(heads) > 1:
        raise CostError("source has conflicting receipt frontiers")
    return selected[next(iter(heads))] if heads else None


def _context_receipt(receipts, entries, binding, profile, cursor, gaps):
    from avo.avo_state import now_iso

    row, _, temporal = entries[-1]
    source, session, epoch = _lineage(row)
    previous = _receipt_frontier(receipts, _lineage(row))
    value = {
        "profileId": profile["profileId"],
        "bindingId": binding["bindingId"],
        "sourceInstanceId": source,
        "sourceSessionId": session,
        "counterEpoch": epoch,
        "predecessorReceiptId": previous["receiptId"] if previous else None,
        "watermark": {"kind": "normalized-cursor-v1", "value": _compact(cursor)},
        "observationKeys": [key for _, key, _ in entries if key is not None],
        "baseline": temporal["baseline"],
        "lifecycle": {"state": "unknown", "reference": None},
        "flush": {"status": "unknown", "reference": None},
        "interval": {
            "sourceSessionId": session,
            "counterEpoch": epoch,
            "start": {"kind": "event", "reference": temporal["start"]},
            "end": {"kind": "event", "reference": row["requestId"]},
        },
        "gaps": sorted(set(gaps + [gap for _, _, t in entries for gap in t["gaps"]])),
        "collectedAt": now_iso(),
    }
    value["receiptId"] = content_hash(value)
    return value


def _compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _cursor_frontier(receipts):
    cursors = {}
    for receipt in receipts:
        if receipt["watermark"]["kind"] == "normalized-cursor-v1":
            cursor = json.loads(receipt["watermark"]["value"])
            cursors[content_hash(cursor)] = cursor
    parents = {c.get("previous") for c in cursors.values()}
    heads = set(cursors) - parents
    if len(heads) > 1:
        raise CostError("source has conflicting read cursors")
    return cursors[next(iter(heads))] if heads else None


def _read_cursor(stream, stat, previous, shape):
    probe = stream.read(min(4096, COLLECTION_BYTE_LIMIT // 4, stat.st_size))
    source = content_hash([stat.st_dev, stat.st_ino])
    cursor = {"shape": shape, "source": source, "offset": 0, "boundarySeen": False}
    gaps = []
    if previous:
        cursor["previous"] = content_hash(previous)
        reason = _source_change(previous, source, probe, stat.st_size)
        if reason:
            gaps.append(reason)
        else:
            cursor.update(
                offset=previous["offset"], boundarySeen=previous["boundarySeen"]
            )
    cursor["prefixBytes"] = len(probe)
    cursor["prefixHash"] = content_hash(probe.hex())
    cursor["size"] = stat.st_size
    cursor["modified"] = stat.st_mtime_ns
    return cursor, gaps, len(probe), probe


def _source_change(previous, source, probe, size):
    if previous["source"] != source:
        return "source-rotated"
    if previous["offset"] > size:
        return "source-truncated"
    count = previous["prefixBytes"]
    if (
        len(probe) < count
        or content_hash(probe[:count].hex()) != previous["prefixHash"]
    ):
        return "source-reexported"
    return None


def _jsonl_chunk(stream, cursor, used, size):
    records, gaps = [], []
    stream.seek(cursor["offset"])
    while len(records) < COLLECTION_RECORD_LIMIT and used < COLLECTION_BYTE_LIMIT:
        start = stream.tell()
        limit = min(COLLECTION_RECORD_BYTE_LIMIT + 1, COLLECTION_BYTE_LIMIT - used)
        raw = stream.readline(limit)
        used += len(raw)
        if not raw:
            break
        issue = _record_issue(raw, stream.tell(), size)
        if issue:
            gaps.append(issue)
            break
        try:
            row = json.loads(raw)
            validate("observation", row)
        except (ValueError, TypeError):
            gaps.append("source-record-invalid")
            break
        records.append((row, stream.tell(), start))
    if records and records[-1][1] < size and not gaps:
        gaps.append("budget-incomplete")
    return records, gaps


def _record_issue(raw, end, size):
    if len(raw) > COLLECTION_RECORD_BYTE_LIMIT:
        return "source-record-too-large"
    if not raw.endswith(b"\n"):
        return "source-partial-record" if end == size else "budget-incomplete"
    return None


def _array_chunk(stream, stat, cursor, used):
    remaining = COLLECTION_BYTE_LIMIT - used
    if stat.st_size > remaining:
        raise CostError("automatic array collection requires a bounded scoped export")
    stream.seek(0)
    value = json.loads(stream.read(remaining))
    rows = value if isinstance(value, list) else value.get("observations")
    if not isinstance(rows, list) or len(rows) > 100000:
        raise CostError("invalid bounded source array")
    start = cursor["offset"]
    selected = rows[start : start + COLLECTION_RECORD_LIMIT]
    for row in selected:
        validate("observation", row)
        if len(_compact(row).encode()) > COLLECTION_RECORD_BYTE_LIMIT:
            raise CostError("source record exceeds collection limit")
    records = [(row, start + i + 1, start + i) for i, row in enumerate(selected)]
    gaps = ["budget-incomplete"] if start + len(selected) < len(rows) else []
    return records, gaps


def _read_chunk(binding, profile, previous):
    path = Path(binding["source"])
    stat = path.stat()
    shape = profile["sourceFormat"]
    with path.open("rb") as stream:
        cursor, gaps, used, probe = _read_cursor(stream, stat, previous, shape)
        _effective_cursor(cursor, previous, binding, stat, gaps)
        if shape == "normalized-jsonl":
            records, issues = _jsonl_chunk(stream, cursor, used, stat.st_size)
        else:
            records, issues = _array_chunk(stream, stat, cursor, used)
    after = path.stat()
    if (stat.st_ino, stat.st_size, stat.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise CostError("source changed during bounded collection")
    return records, cursor, gaps + issues, probe


def _effective_cursor(cursor, previous, binding, stat, gaps):
    ending = binding.get("endBoundary")
    narrowed = previous and previous.get("endBoundary") != ending
    rewritten = (
        previous
        and previous.get("size") == stat.st_size
        and previous.get("modified") != stat.st_mtime_ns
    )
    if narrowed or rewritten:
        cursor.update(offset=0, boundarySeen=False)
        gaps.append("source-scope-narrowed" if narrowed else "source-reexported")
    cursor["endBoundary"] = ending


def _validate_context_row(row, fact, profile):
    from avo.cost_store import _profile_counter_semantics

    expected_host = ("host-agent", fact["agent"]["family"], fact["agent"]["version"])
    if (row["serviceClass"], row["agent"], row["agentVersion"]) != expected_host:
        raise CostError("request source differs from accepted host context")
    for field in ("sourceInstanceId", "sourceSessionId", "counterEpoch"):
        if field == "counterEpoch" and fact["scope"].get(field) is None:
            continue
        if field in fact["scope"] and row.get(field) != fact["scope"][field]:
            raise CostError("source row differs from accepted context scope")
    _profile_counter_semantics(row, profile)


def _temporal_state(view, receipts):
    state = {}
    rows = {
        _lineage(row) + (row["requestId"],): row
        for batch in view["batches"]
        for row in batch["observations"]
    }
    for lineage in {_lineage(r) for r in receipts}:
        receipt = _receipt_frontier(receipts, lineage)
        reference = (receipt["interval"].get("end") or {}).get("reference")
        state[lineage] = {
            "row": rows.get(lineage + (reference,)),
            "baseline": receipt["baseline"],
            "broken": "counter-epoch-required" in receipt["gaps"],
        }
    return state


def _batch_keys(batch):
    from avo.cost_store import CostStore

    return batch.get("observationKeys", CostStore.keys_for(batch["observations"]))


def _reduced(previous, row):
    if row["sequence"] <= previous["sequence"]:
        return True
    return any(
        value is not None
        and previous["tokens"].get(key) is not None
        and value < previous["tokens"][key]
        for key, value in row["tokens"].items()
    )


def _temporal(row, binding, profile, state):
    current = state.setdefault(_lineage(row), {})
    gaps = []
    baseline = {"status": "not-applicable", "reference": None}
    previous = current.get("row")
    if profile["semantics"]["counter"] == "cumulative":
        baseline = _baseline(row, binding, current)
        if previous and _reduced(previous, row):
            current["broken"] = True
        if current.get("broken"):
            gaps.append("counter-epoch-required")
        if baseline["status"] == "missing":
            gaps.append("baseline-missing")
    if _inherited_without_boundary(row, binding, profile):
        gaps.append("inheritance-boundary-missing")
    current.update(row=row, baseline=baseline)
    start = row["requestId"]
    if profile["semantics"]["counter"] == "cumulative":
        start = previous["requestId"] if previous else baseline["reference"] or start
    return {"baseline": baseline, "gaps": gaps, "start": start}


def _baseline(row, binding, current):
    known = current.get("baseline")
    if known and known["status"] == "accepted":
        return known
    values = [v for v in row["tokens"].values() if v is not None]
    if row["requestId"] == binding["boundary"] or (
        values and all(v == 0 for v in values)
    ):
        return {"status": "accepted", "reference": row["requestId"]}
    return {"status": "missing", "reference": None}


def _inherited_without_boundary(row, binding, profile):
    inherited = row.get("parentSessionId") or row.get("parentSourceInstanceId")
    return bool(
        inherited
        and profile["semantics"]["fork"] != "new-activities"
        and binding["boundary"] == "beginning"
    )


def _packet(fact, profile, entries, receipts):
    return {
        "schemaVersion": "2.0.0",
        "operationId": "collect-context:"
        + content_hash(
            {"factId": fact["factId"], "receipts": [r["receiptId"] for r in receipts]}
        ),
        "accountingVideoId": fact["accountingVideoId"],
        "profileId": profile["profileId"],
        "observations": [row for row, key, _ in entries if key is not None],
        "evidence": [
            _context_evidence(row, key, fact, profile, temporal)
            for row, key, temporal in entries
            if key is not None
        ],
        "receipts": receipts,
    }


def _admit_records(store, records, fact, binding, profile, cursor, state, accepted):
    entries, gaps, size, receipt_sizes = [], [], 512, {}
    for row, end, start in records:
        if row["sourceSessionId"] != binding["sourceSessionId"]:
            cursor["offset"] = end
            continue
        reached = cursor["boundarySeen"] or binding["boundary"] == "beginning"
        if row["requestId"] == binding["boundary"]:
            reached = row.get("measurementKind") == "cumulative"
            cursor["boundarySeen"] = True
        if reached:
            entry, cost = _admit_row(
                store, row, fact, binding, profile, state, accepted
            )
            receipt_cost = _receipt_cost(entry, binding, profile, cursor)
            added_receipt = max(0, receipt_cost - receipt_sizes.get(_lineage(row), 0))
            cost += added_receipt
            if size + cost > COLLECTION_PACKET_BYTE_LIMIT:
                cursor["offset"] = start
                gaps.append("budget-incomplete")
                break
            size += cost
            receipt_sizes[_lineage(row)] = receipt_cost
            entries.append(entry)
        else:
            entries.append((row, None, _pending_temporal(row, profile)))
        cursor["offset"] = end
        cursor["boundarySeen"] = cursor["boundarySeen"] or reached
        if row["requestId"] == binding.get("endBoundary"):
            cursor["ended"] = True
            break
    gaps.extend(_cursor_gaps(cursor, binding, entries, records))
    return entries, gaps


def _cursor_gaps(cursor, binding, entries, records):
    gaps = []
    if not cursor["boundarySeen"] and binding["boundary"] != "beginning":
        gaps.append("source-boundary-pending")
    if binding.get("endBoundary") and not cursor.get("ended"):
        gaps.append("source-end-boundary-pending")
    if records and not entries:
        gaps.append("source-session-unavailable")
    return gaps


def _receipt_cost(entry, binding, profile, cursor):
    receipt = _context_receipt([], [entry], binding, profile, cursor, [])
    # Reserve the bounded cursor, predecessor and gap fields before reading more rows.
    return len(_compact(receipt).encode()) + 1200


def _pending_temporal(row, profile):
    cumulative = profile["semantics"]["counter"] == "cumulative"
    return {
        "baseline": {
            "status": "missing" if cumulative else "not-applicable",
            "reference": None,
        },
        "gaps": [],
        "start": row["requestId"],
    }


def _admit_row(store, row, fact, binding, profile, state, accepted):
    row = _binding_context(row, binding)
    _validate_context_row(row, fact, profile)
    key = store.keys_for([row])[0]
    if content_hash(key) in accepted:
        temporal = _known_temporal(row, binding, profile, state)
        return (row, None, temporal), 0
    temporal = _temporal(row, binding, profile, state)
    metadata = _context_evidence(row, key, fact, profile, temporal)
    return (row, key, temporal), len(_compact([row, metadata, key]).encode())


def _known_temporal(row, binding, profile, state):
    current = state.get(_lineage(row), {})
    if (
        not current.get("row")
        and row["requestId"] == binding["boundary"]
        and profile["semantics"]["counter"] == "cumulative"
    ):
        return _temporal(row, binding, profile, state)
    return {
        "baseline": current.get(
            "baseline", {"status": "not-applicable", "reference": None}
        ),
        "gaps": ["counter-epoch-required"] if current.get("broken") else [],
        "start": row["requestId"],
    }


def _collection_packet(store, view, fact, binding, profile, receipts, previous):
    records, cursor, gaps, probe = _read_chunk(binding, profile, previous)
    accepted = {content_hash(k) for b in view["batches"] for k in _batch_keys(b)}
    entries, issues = _admit_records(
        store,
        records,
        fact,
        binding,
        profile,
        cursor,
        _temporal_state(view, receipts),
        accepted,
    )
    temporal_gaps = [gap for _, _, temporal in entries for gap in temporal["gaps"]]
    read_gaps = sorted(set(gaps + issues))
    gaps = sorted(set(read_gaps + temporal_gaps))
    _seal_cursor(cursor, probe, profile, gaps)
    if _same_cursor(previous, cursor) or not entries:
        return None, gaps
    groups = {}
    for entry in entries:
        groups.setdefault(_lineage(entry[0]), []).append(entry)
    new_receipts = [
        _context_receipt(receipts, group, binding, profile, cursor, read_gaps)
        for group in groups.values()
    ]
    packet = _packet(fact, profile, entries, new_receipts)
    if len(_compact(packet).encode()) > COLLECTION_PACKET_BYTE_LIMIT:
        raise CostError("bounded collection packet exceeds metadata budget")
    return packet, gaps


def _seal_cursor(cursor, probe, profile, gaps):
    cursor["gaps"] = gaps
    cursor["prefixBytes"] = (
        min(len(probe), cursor["offset"])
        if profile["sourceFormat"] == "normalized-jsonl"
        else len(probe)
    )
    cursor["prefixHash"] = content_hash(probe[: cursor["prefixBytes"]].hex())


def _same_cursor(previous, cursor):
    if not previous:
        return False
    return {k: v for k, v in previous.items() if k != "previous"} == {
        k: v for k, v in cursor.items() if k != "previous"
    }


def _collect_context_requests(store, view, fact):
    binding, profile = _context_source(store, view, fact)
    receipts = _source_receipts(view, binding, profile)
    previous = _cursor_frontier(receipts)
    if previous and previous.get("ended"):
        return 0, []
    packet, gaps = _collection_packet(
        store, view, fact, binding, profile, receipts, previous
    )
    imported = store.ingest_packet(packet)["imported"] if packet is not None else 0
    return imported, [{"code": gap, "bindingId": binding["bindingId"]} for gap in gaps]


def collect_context(store, context_result):
    """Collect only the exact accepted caller's authorized request source."""
    store.assert_writable()
    from avo.cost_history import remember

    diagnostics = []
    imported = 0
    try:
        view = store.capture()
        fact = _accepted_context(view, context_result, store.identity() or {})
        try:
            remember(store)
        except OSError:
            diagnostics.append({"code": "history-locator-unavailable"})
        if fact.get("sourceAttachment"):
            imported, source_diagnostics = _collect_context_requests(store, view, fact)
            diagnostics.extend(source_diagnostics)
    except PermissionError:
        diagnostics.append({"code": "context-source-denied"})
    except FileNotFoundError:
        diagnostics.append({"code": "context-source-missing"})
    except OSError:
        diagnostics.append({"code": "context-source-unavailable"})
    except (ValueError, KeyError, TypeError):
        diagnostics.append({"code": "context-source-incompatible"})
    return {
        "status": "partial" if diagnostics else "ok",
        "imported": imported,
        "diagnostics": diagnostics,
    }


def _manual_fact(view, fact_id):
    matches = [fact for fact in view["participations"] if fact["factId"] == fact_id]
    if len(matches) != 1:
        raise CostError("manual report requires an existing exact participation fact")
    fact = matches[0]
    agent = fact.get("agent") or {}
    if fact["mode"] != "agent" or not agent.get("family") or not agent.get("surface"):
        raise CostError(
            "manual report requires an explicitly declared agent and surface"
        )
    return fact


def _manual_profile(fact):
    from avo.cost_profiles import profile_id, validate_profile

    profile = {
        "schemaVersion": "2.0.0",
        "agent": fact["agent"]["family"],
        "surface": fact["agent"]["surface"],
        "versions": [],
        "sourceFormat": "avo-manual-report-v2",
        "parserVersion": "1",
        "parserDigest": content_hash("avo/manual-report-v2/1"),
        "fixtureDigests": [],
        "references": [],
        "capability": "manual-only",
        "semantics": {
            "counter": "unknown",
            "categoryOverlap": {},
            "aggregateScope": "unknown",
            "revision": "immutable",
            "resume": "unknown",
            "fork": "unknown",
            "reset": "not-applicable",
            "finality": "unknown",
        },
        "identityFields": ["sourceInstanceId", "sourceSessionId", "requestId"],
        "allowedFields": [
            "tokens",
            "semantics",
            "amounts",
            "model",
            "serviceProvider",
            "billingMode",
            "occurredAt",
        ],
        "limitations": [
            "Explicit user-reported metadata; no native source, served model, counter baseline or final flush is certified."
        ],
        "qualification": {"kind": "synthetic", "evidenceRefs": []},
    }
    profile["profileId"] = profile_id(profile)
    return validate_profile(profile)


def _validate_manual_scope(row, fact):
    agent = fact["agent"]
    if row["serviceClass"] != "host-agent" or row["agent"] != agent["family"]:
        raise CostError("manual report differs from the declared agent scope")
    if agent.get("version") is not None and row["agentVersion"] != agent["version"]:
        raise CostError("manual report differs from the declared agent version")
    for field in ("sourceInstanceId", "sourceSessionId", "counterEpoch"):
        expected = fact["scope"].get(field)
        if expected is not None and row.get(field) != expected:
            raise CostError("manual report differs from the declared source scope")
    session = agent.get("sourceSessionId")
    if session is not None and row["sourceSessionId"] != session:
        raise CostError("manual report differs from the declared source session")


def _manual_evidence(row, key, fact, profile):
    from avo.cost_participation import evidence_id

    temporal = {
        "start": row["requestId"],
        "gaps": [],
        "baseline": {"status": "not-applicable", "reference": None},
    }
    metadata = _context_evidence(row, key, fact, profile, temporal)
    metadata.update(nature="manual", acquisition="manual", modelBasis="unknown")
    metadata["attribution"]["basis"] = (
        "explicit user manual report for exact participation fact"
    )
    metadata["evidenceId"] = evidence_id(metadata)
    return metadata


def _manual_packet(store, view, rows, fact, profile, operation_id):
    rows = [{**deepcopy(row), "measurementKind": "manual"} for row in rows]
    evidence = []
    for row, key in zip(rows, store.keys_for(rows)):
        _validate_manual_scope(row, fact)
        evidence.append(_manual_evidence(row, key, fact, profile))
    packet = {
        "schemaVersion": "2.0.0",
        "operationId": operation_id,
        "accountingVideoId": store.identity()["accountingVideoId"],
        "profileId": profile["profileId"],
        "observations": rows,
        "evidence": evidence,
        "receipts": _manual_receipts(store, view, rows, profile, operation_id),
    }
    validate("packet", packet)
    if len(_compact(packet).encode()) > 32 * 1024 * 1024:
        raise CostError("manual cost packet exceeds 32 MiB; supply a scoped group")
    return packet


def _manual_receipts(store, view, rows, profile, operation_id):
    previous = next(
        (b for b in view["batches"] if b.get("operationId") == operation_id), None
    )
    if previous is not None:
        return deepcopy(previous["receipts"])
    receipts = [
        r
        for b in view["batches"]
        for r in b.get("receipts", [])
        if r["profileId"] == profile["profileId"] and r["bindingId"] is None
    ]
    groups = {}
    for row, key in zip(rows, store.keys_for(rows)):
        groups.setdefault(_lineage(row), []).append((row, key))
    return [
        _manual_receipt(group, receipts, profile, operation_id)
        for group in groups.values()
    ]


def _manual_receipt(group, previous, profile, operation_id):
    from avo.avo_state import now_iso

    row = group[-1][0]
    frontier = _receipt_frontier(previous, _lineage(row))
    source, session, epoch = _lineage(row)
    value = {
        "profileId": profile["profileId"],
        "bindingId": None,
        "sourceInstanceId": source,
        "sourceSessionId": session,
        "counterEpoch": epoch,
        "predecessorReceiptId": frontier["receiptId"] if frontier else None,
        "watermark": {"kind": "manual-report", "value": operation_id},
        "observationKeys": [key for _, key in group],
        "baseline": {"status": "not-applicable", "reference": None},
        "lifecycle": {"state": "unknown", "reference": None},
        "flush": {"status": "unknown", "reference": None},
        "interval": {
            "sourceSessionId": session,
            "counterEpoch": epoch,
            "start": {"kind": "event", "reference": group[0][0]["requestId"]},
            "end": {"kind": "event", "reference": row["requestId"]},
        },
        "gaps": [],
        "collectedAt": now_iso(),
    }
    value["receiptId"] = content_hash(value)
    return value


def report_manual(store, rows, *, participation_fact_id, operation_id):
    """Public manual bootstrap; its profile never certifies native measurement."""
    store.assert_writable()
    from avo.cost_store import (
        _assert_exclusive_claims,
        _packet_claims,
        _validate_packet,
    )

    validate(
        "manual-request",
        {
            "schemaVersion": "2.0.0",
            "operationId": operation_id,
            "participationFactId": participation_fact_id,
            "observations": rows,
        },
    )
    if not rows:
        raise CostError("manual report requires explicit usage metadata")
    view = store.capture()
    fact = _manual_fact(view, participation_fact_id)
    profile = _manual_profile(fact)
    packet = _manual_packet(store, view, rows, fact, profile, operation_id)
    candidate = {**view, "profiles": [*view["profiles"], profile]}
    _validate_packet(packet, candidate, False)
    if not any(batch.get("operationId") == operation_id for batch in view["batches"]):
        _assert_exclusive_claims(store, _packet_claims(packet))
        store.append_record("profiles", profile)
    result = store.ingest_packet(packet)
    return {
        "schemaVersion": "2.0.0",
        "accountingVideoId": fact["accountingVideoId"],
        "profileId": profile["profileId"],
        "participationId": fact["participationId"],
        "factId": fact["factId"],
        **result,
    }


def source_fingerprint(path):
    return content_hash({"source": str(Path(path).resolve())})
