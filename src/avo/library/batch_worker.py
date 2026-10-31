"""One admitted item at a time, with durable limits and reusable native payloads."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from avo.library.moves import load, save
from avo.library.rules import (
    observation,
    read_request,
    reject,
    safe_path,
    verify_source,
)
from avo.library.usage import record_usage
from avo.timeline.contracts import content_hash
from avo.transcribe import (
    ENGINE,
    LocalTranscriber,
    atomic_write_json,
    inspect_cache,
    validate_transcript_payload,
)


def _output(service, record, lock, config):
    key = content_hash(
        {
            "model": config["model"],
            "language": config["language"],
            "engine": config["engineVersion"],
            "source": lock["sha256"],
        }
    )[:32]
    relative = f"edit/library/transcripts/{record['id']}/{key}.json"
    return relative, safe_path(service.root, relative)


def _payload(path, fingerprint, config):
    if (
        inspect_cache(
            path, fingerprint, config["model"], language_code=config["language"]
        )
        != "valid"
    ):
        return None
    payload = read_request(path, limit=64 * 1024 * 1024)
    validate_transcript_payload(payload)
    if (
        payload["engine_version"] != config["engineVersion"]
        or len(payload["words"]) > 100000
    ):
        return None
    return payload


def _runtime(config, factory):
    return factory(
        model=config["model"],
        model_dir=Path(config["modelDir"]),
        device=config["device"],
        compute_type=config["computeType"],
        language=config["language"],
        num_workers=1,
        cpu_threads=config["limits"]["cpuThreads"],
    )


def _validate_output(payload, actual, record, config):
    validate_transcript_payload(payload)
    fields = (
        payload["model"] == config["model"],
        payload["source"]["sha256"] == actual["sha256"],
        payload["engine"] == ENGINE,
        payload["engine_version"] == config["engineVersion"],
    )
    if not all(fields):
        reject(
            "LIB_TRANSCRIPT_INVALID",
            "Worker payload differs from approved source/model/runtime",
        )
    if config["language"] != "auto" and payload["language_code"] != config["language"]:
        reject("LIB_TRANSCRIPT_INVALID", "Worker language differs from approval")
    duration = record["metadata"].get("durationSeconds")
    if duration is not None and any(
        word["end"] > duration for word in payload["words"]
    ):
        reject("LIB_TRANSCRIPT_INVALID", "Worker transcript exceeds source duration")
    if (
        len(payload["words"]) > 100000
        or len(json.dumps(payload).encode()) > 64 * 1024 * 1024
    ):
        reject("LIB_INPUT_TOO_LARGE", "Worker transcript exceeds reserved output size")


def _process(service, state, record, lock, config, runtime, factory):
    source = safe_path(service.root, record["path"])
    actual = verify_source(source, lock)
    relative, output = _output(service, record, actual, config)
    fingerprint = {
        "path": str(source),
        "sha256": actual["sha256"],
        "size_bytes": actual["sizeBytes"],
        "mtime_ns": actual["mtimeNs"],
    }
    payload = _payload(output, fingerprint, config)
    reused = payload is not None
    attempt = uuid4().hex
    if not reused:
        if shutil.disk_usage(service.root).free < 64 * 1024 * 1024:
            reject(
                "LIB_BUDGET_EXHAUSTED",
                "Insufficient free space for reserved transcript publication",
                "conflict",
            )
        runtime = runtime or _runtime(config, factory)
        runtime.language = config["language"]
        payload = runtime.transcribe(source, fingerprint)
        payload["requested_language"] = config["language"]
        verify_source(source, lock)
        _validate_output(payload, actual, record, config)
        atomic_write_json(output, payload)
    _validate_output(payload, actual, record, config)
    reference = {
        "path": relative,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "sourceSha256": actual["sha256"],
        "model": config["model"],
        "requestedLanguage": config["language"],
        "observation": observation(source),
    }
    previous = record.get("transcript") or {}
    if reused:
        reference["usageRefs"] = previous.get("usageRefs", [])
    else:
        reference["usageRefs"] = [
            record_usage(service.store, state["operationId"], attempt, record["id"])
        ]
    return {
        "status": "reused" if reused else "succeeded",
        "createdBytes": 0 if reused else output.stat().st_size,
        "output": reference,
        "attemptId": attempt,
    }, runtime


def _check_run(service, state, packet):
    from avo.library.batch import resolve_configuration

    decision = service.store.get(state["decisionRef"])
    if (
        decision["decision"] != "approved"
        or decision["packetHash"] != state["packetRef"]["sha256"]
    ):
        reject(
            "LIB_APPROVAL_REQUIRED", "Worker needs the exact approved batch", "conflict"
        )
    if (
        packet["kind"] != "batch"
        or packet["root"] != str(service.root)
        or packet["provider"] != service.provider
    ):
        reject("LIB_INVALID_REQUEST", "Worker library context differs")
    head = service.store.head()
    _decision_selection(state, packet, decision, head)
    current = resolve_configuration(service, packet["config"]["request"])
    fields = (
        "model",
        "modelDir",
        "device",
        "computeType",
        "engineVersion",
        "policyHash",
        "routingToken",
    )
    if any(current[key] != packet["config"][key] for key in fields):
        reject("LIB_STALE_PROPOSAL", "Local model/route configuration changed", "stale")


def _decision_selection(state, packet, decision, head):
    if (
        state["selected"] != [item["recordingId"] for item in packet["selected"]]
        or decision["libraryId"] != head["libraryId"]
    ):
        reject(
            "LIB_APPROVAL_REQUIRED",
            "Worker selection differs from the approval",
            "conflict",
        )
    approved = {item["actionId"] for item in packet["selected"]}
    if set(decision["approvedIds"]) != approved:
        reject(
            "LIB_APPROVAL_REQUIRED",
            "Decision does not cover the worker selection",
            "conflict",
        )


def _elapsed(state, clock):
    checkpoint = state["result"].get("checkpoint")
    if checkpoint is not None:
        delta = clock() - checkpoint
        if delta < 0:
            reject(
                "LIB_BUDGET_EXHAUSTED",
                "Cannot recover processing allowance after clock reset",
                "conflict",
            )
        state["elapsedSeconds"] += delta
    state["result"]["checkpoint"] = clock()
    return state["elapsedSeconds"]


def _publish(service, state):
    head = service.store.head()
    inventory = deepcopy(service.store.get(head["inventoryRef"]))
    for record in inventory["recordings"]:
        item = state["result"]["items"].get(record["id"], {})
        if item.get("output"):
            record["transcript"] = item["output"]
    ref = service.store.put("inventory", inventory)
    # Source versions remain unchanged; existing move approvals still bind the old inventory.
    service.store.publish(
        {**head, "inventoryRef": ref, "activeOperation": None}, head["headHash"]
    )


def run(
    service,
    operation_id,
    *,
    runtime_factory=LocalTranscriber,
    after_item=None,
    clock=time.monotonic,
):
    from avo.library.batch import result_for

    service.writable()
    with service.store.exclusive():
        state = load(service, operation_id)
        if service.store.head()["activeOperation"] != operation_id:
            reject(
                "LIB_RESOURCE_BUSY", "Worker is not the active operation", "conflict"
            )
        packet = service.store.get(state["packetRef"])
        _check_run(service, state, packet)
        _run_items(service, state, packet, runtime_factory, after_item, clock)
        # Clean pauses exclude subsequent idle time; an interrupted running checkpoint
        # remains a conservative elapsed bound and cannot reset the approved allowance.
        state["result"]["checkpoint"] = None
        save(service, state)
        _publish(service, state)
        return result_for(service, state)


def _run_items(service, state, packet, factory, after_item, clock):
    locks = {entry["recordingId"]: entry["fingerprint"] for entry in packet["locks"]}
    config = packet["config"]
    runtime = None
    state["failed"] = []
    for record in packet["selected"]:
        if record["id"] in state["completed"]:
            continue
        if service.store.cancelled(state["operationId"]):
            state["status"] = "cancelled"
            return
        if _elapsed(state, clock) >= config["limits"]["maxProcessingSeconds"]:
            state["status"] = "partial"
            state["failed"].append(
                {
                    "code": "LIB_BUDGET_EXHAUSTED",
                    "message": "No remaining processing allowance",
                }
            )
            return
        state["result"]["current"] = record["path"]
        save(service, state)
        try:
            runtime = _one_item(
                service, state, record, locks[record["id"]], config, runtime, factory
            )
        except (OSError, ValueError, RuntimeError) as exc:
            state["failed"].append(
                {
                    "recordingId": record["id"],
                    "code": getattr(exc, "code", "LIB_TRANSCRIPT_FAILED"),
                    "message": str(exc),
                }
            )
            state["status"] = "partial"
            _elapsed(state, clock)
            return
        _elapsed(state, clock)
        save(service, state)
        if after_item:
            after_item(record)
    state["status"] = "completed"


def _one_item(service, state, record, lock, config, runtime, factory):
    if record["metadata"].get("audio") is False:
        verify_source(safe_path(service.root, record["path"]), lock)
        item = {"status": "skipped", "reason": "Recording has no audio"}
    else:
        item, runtime = _process(service, state, record, lock, config, runtime, factory)
    state["result"]["items"][record["id"]] = item
    state["completed"].append(record["id"])
    return runtime
