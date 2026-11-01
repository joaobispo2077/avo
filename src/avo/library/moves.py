"""Source-bound move approval, durable execution, reconciliation and reversal."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from avo.library.inventory import summarize
from avo.library.rules import (
    observation,
    read_request,
    reject,
    safe_path,
    source_lock,
    validate,
    verify_source,
)
from avo.library.store import publish_json
from avo.timeline.store import now_iso


def eligible(service, action):
    source = safe_path(service.root, action["from"])
    target = safe_path(service.root, action["to"])
    if source == target or action["from"].casefold() == action["to"].casefold():
        reject("LIB_INVALID_REQUEST", "Same-path and case-only moves are unsupported")
    _check_source_ownership(service.root, source)
    if target.exists():
        reject("LIB_DESTINATION_EXISTS", "Destination is occupied", "conflict")
    return source, target


def _check_source_ownership(root, source):
    for parent in [source.parent, *source.parent.parents]:
        if not parent.is_relative_to(root):
            break
        if (parent / "avo.project.json").exists() or (
            parent / "edit/timeline"
        ).exists():
            reject(
                "LIB_REFERENCE_OWNED",
                "Existing project sources stay at registered locations",
                "conflict",
            )
        if (
            any(parent.glob("*.prproj"))
            or any(parent.glob("*.drp"))
            or any(parent.glob("*.fcpxml"))
        ):
            reject(
                "LIB_REFERENCE_OWNED",
                "NLE ownership cannot be safely relinked",
                "conflict",
            )


def _current_proposal(service, identifier, head):
    ref, proposal = service.store.lookup("proposal", identifier)
    if ref != head["proposalRef"]:
        reject("LIB_STALE_PROPOSAL", "Prepare the currently selected proposal", "stale")
    if "@" in identifier and identifier.split("@", 1)[1] != str(proposal["revision"]):
        reject("LIB_STALE_PROPOSAL", "Proposal revision differs", "stale")
    return ref, proposal


def _selected_actions(proposal, selection):
    wanted = set(selection["actionIds"])
    selected = [a for a in proposal["actions"] if a["actionId"] in wanted]
    if len(selected) != len(wanted) or any(a["status"] != "move" for a in selected):
        reject("LIB_INVALID_REQUEST", "Select only eligible proposed action IDs")
    declared = set(selection["unboundSourceIds"])
    if declared != {a["recordingId"] for a in selected}:
        reject(
            "LIB_OWNERSHIP_UNKNOWN",
            "Declare exact selected unbound recording ownership",
            "conflict",
        )
    return selected


def _check_move_topology(selected):
    from_paths = {a["from"].casefold() for a in selected}
    targets = [a["to"].casefold() for a in selected]
    if len(targets) != len(set(targets)) or from_paths.intersection(targets):
        reject(
            "LIB_INVALID_REQUEST",
            "Move chains, cycles and duplicate destinations are unsupported",
        )


def _lock_selected_sources(service, selected, records):
    locks = []
    for action in selected:
        service.activity(
            len(locks), len(selected), action["from"], phase="source-verification"
        )
        source, _ = eligible(service, action)
        recording = records[action["recordingId"]]
        if observation(source) != recording["observation"]:
            reject(
                "LIB_SOURCE_CHANGED", "Recording changed since the proposal", "stale"
            )
        locks.append(
            {
                "recordingId": recording["id"],
                "path": recording["path"],
                "version": recording["version"],
                "fingerprint": source_lock(source),
            }
        )
    return locks


def prepare(service, identifier, selection):
    validate("selection", selection)
    service.writable()
    with service.store.exclusive():
        head = service.store.head()
        idle(head)
        ref, proposal = _current_proposal(service, identifier, head)
        inventory = service.store.get(head["inventoryRef"])
        records = {r["id"]: r for r in inventory["recordings"]}
        selected = _selected_actions(proposal, selection)
        _check_move_topology(selected)
        locks = _lock_selected_sources(service, selected, records)
        packet = {
            "packetId": uuid4().hex,
            "kind": "moves",
            "proposalRef": ref,
            "inventoryRef": head["inventoryRef"],
            "selected": selected,
            "locks": locks,
            "config": {
                "headHash": head["headHash"],
                "capabilities": service.capabilities(),
            },
            "estimates": {
                "bytesMoved": sum(x["fingerprint"]["sizeBytes"] for x in locks),
                "seconds": None,
                "basis": "No calibrated move throughput",
            },
            "root": str(service.root),
            "provider": service.provider,
        }
        packet_ref = service.store.put("prepared", packet)
        return {
            "status": "prepared",
            "packetRef": packet_ref,
            "refs": {"prepared": packet_ref},
            "summary": {"selected": len(selected)},
            "estimates": packet["estimates"],
            "capabilities": packet["config"]["capabilities"],
        }


def idle(head):
    if head["activeOperation"]:
        reject(
            "LIB_RESOURCE_BUSY", "Reconcile the active library operation", "conflict"
        )


def approve(service, request):
    validate("decision", request)
    service.writable()
    with service.store.exclusive():
        head = service.store.head()
        idle(head)
        service.check_request(request, head)
        ref, packet = service.store.lookup("prepared", request["packetId"])
        if (
            request["packetHash"] != ref["sha256"]
            or packet["config"]["headHash"] != head["headHash"]
        ):
            reject("LIB_STALE_PROPOSAL", "Prepared approval subject changed", "stale")
        approved = request["approvedIds"]
        selected = [item["actionId"] for item in packet["selected"]]
        if len(approved) != len(set(approved)) or set(approved) != set(selected):
            reject(
                "LIB_INVALID_REQUEST", "Decision must name the exact prepared selection"
            )
        if not request["actor"].strip() or not request["creatorInstruction"].strip():
            reject(
                "LIB_APPROVAL_REQUIRED",
                "Record the explicit creator decision",
                "conflict",
            )
        decision_ref = service.store.put("decision", request)
        return {
            "status": "ok",
            "decisionRef": decision_ref,
            "refs": {"decision": decision_ref},
        }


def approval(service, identifier):
    decision_ref, decision = service.store.lookup("decision", identifier)
    if decision["decision"] != "approved":
        reject(
            "LIB_APPROVAL_REQUIRED",
            "An explicit approved decision is required",
            "conflict",
        )
    packet_ref, packet = service.store.lookup("prepared", decision["packetId"])
    head = service.store.head()
    if (
        packet_ref["sha256"] != decision["packetHash"]
        or packet["root"] != str(service.root)
        or packet["provider"] != service.provider
        or packet["inventoryRef"] != head["inventoryRef"]
        or packet["proposalRef"] != head["proposalRef"]
    ):
        reject("LIB_STALE_PROPOSAL", "Approval no longer matches the library", "stale")
    return packet_ref, packet, decision_ref


def status_path(service, operation_id):
    if len(operation_id or "") != 32 or any(
        c not in "0123456789abcdef" for c in operation_id
    ):
        reject("LIB_INVALID_REQUEST", "Invalid operation ID")
    return service.store.path(f"edit/library/operations/{operation_id}/status.json")


def save(service, state):
    ref = service.store.put("operation", state)
    publish_json(status_path(service, state["operationId"]), ref)
    return ref


def load(service, operation_id):
    ref = read_request(status_path(service, operation_id))
    return service.store.get(ref)


def event(service, state, kind, action, evidence):
    previous = state["previousEvent"]
    sequence = service.store.get(previous)["sequence"] + 1 if previous else 1
    state["previousEvent"] = service.store.put(
        "event",
        {
            "operationId": state["operationId"],
            "sequence": sequence,
            "previous": previous,
            "type": kind,
            "actionId": action["actionId"] if action else None,
            "evidence": evidence,
            "time": now_iso(),
        },
    )
    save(service, state)


def apply(service, identifier, *, fault=None, mover=None):
    service.writable()
    with service.store.exclusive():
        head = service.store.head()
        idle(head)
        packet_ref, packet, decision_ref = approval(service, identifier)
        if packet["kind"] != "moves":
            reject("LIB_INVALID_REQUEST", "Use batch run for a batch approval")
        if mover is None:
            from avo.adapters.media.library_moves import capability

            support = capability(service.root)
            if not support["available"]:
                reject("LIB_MOVE_UNSUPPORTED", support["reason"], "unavailable")
        state = {
            "operationId": uuid4().hex,
            "kind": "moves",
            "packetRef": packet_ref,
            "decisionRef": decision_ref,
            "selected": packet["selected"],
            "completed": [],
            "failed": [],
            "status": "running",
            "startedAt": now_iso(),
            "elapsedSeconds": 0,
            "previousEvent": None,
            "result": {},
        }
        save(service, state)
        service.store.publish(
            {**head, "activeOperation": state["operationId"]}, head["headHash"]
        )
        return execute(service, state, packet, fault=fault, mover=mover)


def execute(service, state, packet, *, fault=None, mover=None):
    if service.progress:
        service.progress.operation_id = state["operationId"]
    if mover is None:
        from avo.adapters.media.library_moves import move_no_replace

        mover = move_no_replace
    locks = {item["recordingId"]: item for item in packet["locks"]}
    state["failed"] = []
    for action in state["selected"]:
        if action["actionId"] in state["completed"]:
            verify_source(
                safe_path(service.root, action["to"]),
                locks[action["recordingId"]]["fingerprint"],
            )
            continue
        if service.store.cancelled(state["operationId"]):
            state["status"] = "cancelled"
            break
        service.activity(
            len(state["completed"]),
            len(state["selected"]),
            action["from"],
            phase="moving",
        )
        try:
            _execute_one(
                service, state, action, locks[action["recordingId"]], mover, fault
            )
        except (OSError, ValueError) as exc:
            state["failed"].append(
                {
                    "actionId": action["actionId"],
                    "code": getattr(exc, "code", "LIB_IO_ERROR"),
                    "message": str(exc),
                }
            )
            state["status"] = "partial"
            save(service, state)
            break
    else:
        state["status"] = "completed"
    save(service, state)
    return finish(service, state)


def _execute_one(service, state, action, lock, mover, fault):
    source = safe_path(service.root, action["from"])
    target = safe_path(service.root, action["to"])
    if target.exists() and not source.exists():
        evidence = verify_source(target, lock["fingerprint"])
    elif source.exists() and not target.exists():
        eligible(service, action)
        verify_source(source, lock["fingerprint"])
        event(service, state, "move-intent", action, lock)
        if fault:
            fault("after-intent", action)
        evidence = mover(
            service.root, action["from"], action["to"], lock["fingerprint"]
        )
        if fault:
            fault("after-move", action)
        verify_source(target, lock["fingerprint"])
    else:
        reject(
            "LIB_RECONCILIATION_REQUIRED",
            "Source/destination state is ambiguous",
            "conflict",
        )
    if fault:
        fault("after-verification", action)
    event(service, state, "move-verified", action, evidence)
    state["completed"].append(action["actionId"])
    save(service, state)
    if fault:
        fault("before-head", action)


def finish(service, state):
    head = service.store.head()
    inventory = deepcopy(service.store.get(head["inventoryRef"]))
    completed = {
        a["recordingId"]: a
        for a in state["selected"]
        if a["actionId"] in state["completed"]
    }
    for record in inventory["recordings"]:
        if record["id"] in completed:
            action = completed[record["id"]]
            record.update(
                path=action["to"],
                observation=observation(safe_path(service.root, action["to"])),
            )
    inventory["summary"] = summarize(inventory["recordings"])
    ref = service.store.put("inventory", inventory)
    active = None if state["status"] == "completed" else state["operationId"]
    head = service.store.publish(
        {**head, "inventoryRef": ref, "activeOperation": active}, head["headHash"]
    )
    return {
        "status": "ok" if state["status"] == "completed" else state["status"],
        "operationId": state["operationId"],
        "headHash": head["headHash"],
        "summary": {
            "completed": len(state["completed"]),
            "failed": len(state["failed"]),
            "movedBytes": sum(
                a.get("sizeBytes", 0)
                for a in state["selected"]
                if a["actionId"] in state["completed"]
            ),
        },
        "refs": {"operation": str(status_path(service, state["operationId"]))},
        "errors": state["failed"],
    }


def resume(service, operation_id, *, fault=None, mover=None):
    service.writable()
    with service.store.exclusive():
        state = load(service, operation_id)
        head = service.store.head()
        if head["activeOperation"] != operation_id:
            reject(
                "LIB_RESOURCE_BUSY",
                "Operation is not the active recovery subject",
                "conflict",
            )
        packet = service.store.get(state["packetRef"])
        state["status"] = "running"
        cancel = service.store.path(f"edit/library/control/{operation_id}.cancel.json")
        cancel.unlink(missing_ok=True)
        return execute(service, state, packet, fault=fault, mover=mover)


def reverse(service, operation_id):
    from avo.library.proposals import checked_destinations, counts

    service.writable()
    with service.store.exclusive():
        head = service.store.head()
        idle(head)
        state = load(service, operation_id)
        original = service.store.get(
            service.store.get(state["packetRef"])["proposalRef"]
        )
        proposal = deepcopy(original)
        proposal.update(
            proposalId=uuid4().hex,
            revision=1,
            parent=None,
            inventoryRef=head["inventoryRef"],
        )
        proposal["actions"] = [
            {
                **a,
                "actionId": uuid4().hex,
                "from": a["to"],
                "to": a["from"],
                "reason": "Explicit reversal proposal",
            }
            for a in state["selected"]
            if a["actionId"] in state["completed"]
        ]
        proposal["summary"] = counts(proposal["actions"])
        checked_destinations(service.root, proposal)
        ref = service.store.put("proposal", proposal)
        head = service.store.publish({**head, "proposalRef": ref}, head["headHash"])
    result = service._review_result(head, proposal)
    return {**result, "proposalRef": ref}
