"""Admission and selected handoff of original-source transcript evidence."""

from __future__ import annotations

import hashlib
from copy import deepcopy

from avo.library.moves import idle
from avo.library.rules import (
    finite_seconds,
    observation,
    read_request,
    reject,
    safe_path,
    source_lock,
    validate,
)
from avo.transcribe import ENGINE, validate_transcript_payload


def admit_transcript(service, recording_id, relative):
    service.writable()
    with service.store.exclusive():
        head = service.store.head()
        idle(head)
        inventory = deepcopy(service.store.get(head["inventoryRef"]))
        record = next(
            (r for r in inventory["recordings"] if r["id"] == recording_id), None
        )
        if record is None:
            reject("LIB_INVALID_REQUEST", "Choose an indexed recording")
        source = safe_path(service.root, record["path"])
        fingerprint = source_lock(source)
        if observation(source) != record["observation"]:
            reject(
                "LIB_SOURCE_CHANGED",
                "Refresh changed source metadata before admission",
                "stale",
            )
        output = safe_path(service.root, relative)
        payload = read_request(output, limit=64 * 1024 * 1024)
        _admission_payload(payload, fingerprint, record)
        record["transcript"] = {
            "path": relative,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "sourceSha256": fingerprint["sha256"],
            "model": payload["model"],
            "requestedLanguage": payload.get(
                "requested_language", payload["language_code"]
            ),
            "observation": record["observation"],
        }
        inventory_ref = service.store.put("inventory", inventory)
        proposal = deepcopy(service.store.get(head["proposalRef"]))
        proposal.update(
            inventoryRef=inventory_ref,
            revision=proposal["revision"] + 1,
            parent=head["proposalRef"],
        )
        proposal_ref = service.store.put("proposal", proposal)
        head = service.store.publish(
            {**head, "inventoryRef": inventory_ref, "proposalRef": proposal_ref},
            head["headHash"],
        )
    return service._review_result(head, proposal)


def _admission_payload(payload, fingerprint, record):
    validate_transcript_payload(payload)
    if (
        payload["engine"] != ENGINE
        or payload["source"]["sha256"] != fingerprint["sha256"]
    ):
        reject(
            "LIB_TRANSCRIPT_INVALID",
            "Transcript is not bound to current original bytes",
        )
    if len(payload["words"]) > 100000:
        reject("LIB_INPUT_TOO_LARGE", "Transcript exceeds segment limit")
    duration = record["metadata"].get("durationSeconds")
    if duration is not None and any(
        word["end"] > duration for word in payload["words"]
    ):
        reject("LIB_TRANSCRIPT_INVALID", "Transcript extends beyond its source")


def select(service, request):
    from avo.library.search import generation_for

    service.writable()
    validate("handoffRequest", request)
    head = service.store.head()
    service.check_request(request, head)
    idle(head)
    if generation_for(service) != request["generation"]:
        reject("LIB_STALE_PROPOSAL", "Search generation has changed", "stale")
    inventory = service.store.get(head["inventoryRef"])
    records = {r["id"]: r for r in inventory["recordings"]}
    selected = [
        _selected(
            service, records, identifier, request.get("ranges", {}).get(identifier)
        )
        for identifier in request["recordingIds"]
    ]
    handoff = {
        "libraryId": head["libraryId"],
        "provider": service.provider,
        "generation": request["generation"],
        "recordings": selected,
        "usageRefs": list(
            {
                ref["sha256"]: ref
                for item in selected
                for ref in (item.get("transcript") or {}).get("usageRefs", [])
            }.values()
        ),
    }
    ref = service.store.put("handoff", handoff)
    return {
        "status": "ok",
        "refs": {"handoff": ref},
        "summary": {"selected": len(selected)},
    }


def _selected(service, records, identifier, selected_range):
    record = records.get(identifier)
    if record is None or record["availability"] != "available":
        reject("LIB_INVALID_REQUEST", "Selected source is unavailable")
    source = safe_path(service.root, record["path"])
    if observation(source) != record["observation"]:
        reject("LIB_SOURCE_CHANGED", "Selected source changed since discovery", "stale")
    fingerprint = source_lock(source)
    if selected_range is not None:
        _range(record, selected_range)
    transcript = record.get("transcript")
    if transcript and transcript["sourceSha256"] != fingerprint["sha256"]:
        reject("LIB_SOURCE_CHANGED", "Selected transcript evidence is stale", "stale")
    return {
        "recordingId": identifier,
        "path": str(source),
        "fingerprint": fingerprint,
        "range": selected_range,
        "restrictions": record["restrictions"],
        "transcript": transcript,
    }


def _range(record, value):
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        reject("LIB_INVALID_REQUEST", "Use an explicit source start/end range")
    start, end = value["start"], value["end"]
    if not finite_seconds(start) or not finite_seconds(end) or end <= start:
        reject("LIB_INVALID_REQUEST", "Invalid original-source range")
    duration = record["metadata"].get("durationSeconds")
    if duration is not None and end > duration:
        reject("LIB_INVALID_REQUEST", "Range exceeds original source duration")
