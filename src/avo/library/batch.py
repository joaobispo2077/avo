"""Approved local batch preparation and supervised adapter dispatch."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from avo.library.moves import approval, idle, load, save, status_path
from avo.library.rules import observation, reject, safe_path, source_lock, validate
from avo.paths import providers_dir, repo_root
from avo.timeline.store import now_iso
from avo.transcribe import package_version, resolve_language

MAX_OUTPUT = 64 * 1024 * 1024


def resolve_configuration(service, request):
    from avo.adapters.base import load_routing_config, routing_token_for_job
    from avo.model_sources import disclosure_for, preflight, resolve_job

    provider = json.loads(
        (providers_dir() / service.provider / "avo.provider.json").read_text(
            encoding="utf-8"
        )
    )
    resolved = resolve_job(
        "transcribe",
        root=repo_root(),
        provider=provider,
        invocation={
            "id": request["model"],
            "runtime": {"device": "cpu", "computeType": "int8"},
        },
    )
    preflight(resolved)
    source = resolved.pin.get("source") or {}
    if source.get("kind") == "endpoint" or not source.get("artifactPath"):
        reject(
            "LIB_PAID_UNAVAILABLE",
            "Library transcription requires prepared local model files",
            "unavailable",
        )
    token = routing_token_for_job(
        load_routing_config(repo_root()), "transcribe", "local"
    )
    if token.split("+")[-1] != "faster-whisper":
        reject(
            "LIB_PAID_UNAVAILABLE",
            "Selected local route cannot enforce this batch contract",
            "unavailable",
        )
    return {
        "model": resolved.id,
        "modelDir": source["artifactPath"],
        "device": "cpu",
        "computeType": "int8",
        "policyHash": resolved.policy_hash,
        "engineVersion": package_version(),
        "routingToken": token,
        "modelDisclosure": disclosure_for(resolved),
    }


def _selection(service, head, request):
    inventory = service.store.get(head["inventoryRef"])
    by_id = {r["id"]: r for r in inventory["recordings"]}
    if any(identifier not in by_id for identifier in request["recordingIds"]):
        reject("LIB_INVALID_REQUEST", "Select indexed recordings only")
    selected, locks = [], []
    for identifier in request["recordingIds"]:
        record = by_id[identifier]
        service.activity(
            len(selected),
            len(request["recordingIds"]),
            record["path"],
            phase="batch-preparation",
        )
        source = safe_path(service.root, record["path"])
        if (
            record["availability"] != "available"
            or observation(source) != record["observation"]
        ):
            reject(
                "LIB_SOURCE_CHANGED",
                "Refresh changed/unavailable recordings before batch preparation",
                "stale",
            )
        fingerprint = source_lock(source)
        selected.append({**record, "recordingId": identifier, "actionId": identifier})
        locks.append(
            {
                "recordingId": identifier,
                "path": record["path"],
                "fingerprint": fingerprint,
            }
        )
    return selected, locks


def _limits(request):
    limits = request["limits"]
    if limits["cpuThreads"] > (os.cpu_count() or 1):
        reject("LIB_INVALID_REQUEST", "CPU thread limit exceeds this machine")
    if limits.get("maxTemporaryBytes", MAX_OUTPUT) < MAX_OUTPUT:
        reject(
            "LIB_BUDGET_EXHAUSTED",
            "Bounded publication needs a 64 MiB maximum output reservation",
            "conflict",
        )
    return limits


def _reusable(service, selected, locks, config):
    from avo.library.batch_worker import _output, _payload

    reused = 0
    for record, lock in zip(selected, locks, strict=True):
        _, output = _output(service, record, lock["fingerprint"], config)
        fingerprint = {"sha256": lock["fingerprint"]["sha256"]}
        try:
            reused += _payload(output, fingerprint, config) is not None
        except (OSError, ValueError, KeyError):
            continue
    return reused


def prepare_batch(service, request):
    if request.get("route") == "paid":
        reject(
            "LIB_PAID_UNAVAILABLE",
            "Paid transcription has no enforceable charge-bound adapter",
            "unavailable",
        )
    validate("batchRequest", request)
    limits = _limits(request)
    service.writable()
    with service.store.exclusive():
        head = service.store.head()
        idle(head)
        service.check_request(request, head)
        selected, locks = _selection(service, head, request)
        configuration = resolve_configuration(service, request)
        _, language, _ = resolve_language(request["language"])
        config = {
            **configuration,
            "headHash": head["headHash"],
            "route": "local",
            "language": language,
            "limits": limits,
            "request": request,
            "timeLimitMode": "stop-new-admissions",
        }
        reusable = _reusable(service, selected, locks, config)
        durations = [r["metadata"].get("durationSeconds") for r in selected]
        estimates = {
            "selected": len(selected),
            "reusable": reusable,
            "newWork": len(selected) - reusable,
            "knownDurationSeconds": sum(d for d in durations if d is not None),
            "unknownDuration": sum(d is None for d in durations),
            "seconds": None,
            "temporaryBytesUpperBound": MAX_OUTPUT,
            "tokens": None,
            "amount": None,
            "coverage": "No attributable agent usage or calibrated runtime estimate",
        }
        packet = {
            "packetId": uuid4().hex,
            "kind": "batch",
            "proposalRef": head["proposalRef"],
            "inventoryRef": head["inventoryRef"],
            "selected": selected,
            "locks": locks,
            "config": config,
            "estimates": estimates,
            "root": str(service.root),
            "provider": service.provider,
        }
        ref = service.store.put("prepared", packet)
    large = (
        len(selected) > 100
        or estimates["knownDurationSeconds"] > 36000
        or estimates["unknownDuration"]
    )
    return {
        "status": "prepared",
        "packetRef": ref,
        "refs": {"prepared": ref},
        "estimates": estimates,
        "warnings": [
            "Large or uncertain batch: review compute, time, space and context before approval"
        ]
        if large
        else [],
        "models": configuration,
    }


def _new_state(service, identifier):
    head = service.store.head()
    idle(head)
    packet_ref, packet, decision_ref = approval(service, identifier)
    if packet["kind"] != "batch":
        reject("LIB_INVALID_REQUEST", "Use apply for move approvals")
    state = {
        "operationId": uuid4().hex,
        "kind": "batch",
        "packetRef": packet_ref,
        "decisionRef": decision_ref,
        "selected": [item["recordingId"] for item in packet["selected"]],
        "completed": [],
        "failed": [],
        "status": "running",
        "startedAt": now_iso(),
        "elapsedSeconds": 0,
        "previousEvent": None,
        "result": {"items": {}},
    }
    save(service, state)
    service.store.publish(
        {**head, "activeOperation": state["operationId"]}, head["headHash"]
    )
    return state


def run_batch(service, identifier, *, dispatcher=None):
    service.writable()
    with service.store.exclusive():
        state = _new_state(service, identifier)
    return _supervise(service, state, dispatcher)


def _dispatch_adapter(service, operation_id):
    prefix = (
        [sys.executable, "run_job"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "avo.adapters.run_job"]
    )
    command = [
        *prefix,
        "transcribe",
        "--label",
        "local",
        "--",
        "--library-batch",
        str(service.root),
        "--provider",
        service.provider,
        "--operation",
        operation_id,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode not in {0, 1, 3, 130}:
        reject(
            "LIB_BATCH_UNAVAILABLE",
            "Local adapter did not complete; inspect operation before retry",
            "unavailable",
        )
    return result


def _supervise(service, state, dispatcher):
    operation_id = state["operationId"]
    created_before = _created_bytes(state)
    if service.progress:
        service.progress.operation_id = operation_id
        service.progress.update(total=len(state["selected"]), phase="transcribing")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(dispatcher or _dispatch_adapter, service, operation_id)
        while not future.done():
            current = load(service, operation_id)
            if service.progress:
                service.progress.update(
                    completed=len(current["completed"]),
                    current=current["result"].get("current"),
                )
            time.sleep(0.2)
        future.result()
    state = load(service, operation_id)
    if state["status"] == "running":
        reject(
            "LIB_RECONCILIATION_REQUIRED",
            "Worker stopped without a terminal outcome",
            "conflict",
        )
    result = result_for(service, state)
    result["summary"]["createdBytes"] = _created_bytes(state) - created_before
    return result


def _created_bytes(state):
    return sum(
        item.get("createdBytes", 0)
        for item in state["result"].get("items", {}).values()
    )


def result_for(service, state):
    items = state["result"].get("items", {})
    return {
        "status": "ok" if state["status"] == "completed" else state["status"],
        "operationId": state["operationId"],
        "summary": {
            "completed": len(state["completed"]),
            "reused": sum(i.get("status") == "reused" for i in items.values()),
            "failed": len(state["failed"]),
            "skipped": sum(i.get("status") == "skipped" for i in items.values()),
        },
        "refs": {"operation": str(status_path(service, state["operationId"]))},
        "usage": {
            "tokens": None,
            "amount": None,
            "coverage": "unavailable",
            "reason": "Local compute is unmetered; no attributable agent usage",
        },
        "errors": state["failed"],
    }


def resume_batch(service, operation_id, *, dispatcher=None):
    service.writable()
    with service.store.exclusive():
        head = service.store.head()
        if head["activeOperation"] not in {None, operation_id}:
            reject(
                "LIB_RESOURCE_BUSY", "Another operation owns these sources", "conflict"
            )
        state = load(service, operation_id)
        if state["kind"] != "batch":
            reject("LIB_INVALID_REQUEST", "Not a batch operation")
        state.update(status="running", failed=[])
        save(service, state)
        service.store.path(f"edit/library/control/{operation_id}.cancel.json").unlink(
            missing_ok=True
        )
        service.store.publish(
            {**head, "activeOperation": operation_id}, head["headHash"]
        )
    return _supervise(service, state, dispatcher)


def run_worker(service, operation_id, **kwargs):
    from avo.library.batch_worker import run

    return run(service, operation_id, **kwargs)


def main(argv=None):
    from avo.library.service import LibraryService

    parser = argparse.ArgumentParser(
        description="Run an already approved local library worker"
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--operation", required=True)
    args = parser.parse_args(argv)
    result = run_worker(LibraryService(args.root, args.provider), args.operation)
    print(json.dumps(result))
    return {"partial": 1, "cancelled": 130}.get(result["status"], 0)


if __name__ == "__main__":
    raise SystemExit(main())
