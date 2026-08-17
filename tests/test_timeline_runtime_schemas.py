from __future__ import annotations

from copy import deepcopy

import pytest

from avo.timeline.contracts import ContractError, content_hash, validate_document

SHA = "a" * 64


def index_document() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "cmap",
        "artifactId": "video:cmap",
        "videoId": "video",
        "provider": "bishop",
        "timelineDomain": "raw-source",
        "headRevisionId": None,
        "approvedRevisionId": None,
        "revisionRefs": [],
        "eventRefs": [],
        "activeState": "valid",
        "updatedAt": "2026-08-13T12:00:00Z",
    }


def revision_document() -> dict:
    body = {
        "schemaVersion": "1.0.0",
        "artifactType": "cmap",
        "artifactId": "video:cmap",
        "revisionId": "cmap-r0001",
        "parentRevisionId": None,
        "createdAt": "2026-08-13T12:00:00Z",
        "actor": {"type": "agent", "id": "codex", "toolVersion": "test"},
        "reason": "initial",
        "timelineDomain": "raw-source",
        "basis": [],
        "snapshot": {"sources": [], "segments": []},
        "diff": [],
        "inputEvidenceRefs": [],
    }
    body["contentSha256"] = content_hash(body)
    return body


def approval_event() -> dict:
    body = {
        "schemaVersion": "1.0.0",
        "eventId": "event-approved-0001",
        "type": "approved",
        "occurredAt": "2026-08-13T12:00:00Z",
        "actor": {"type": "user", "id": "creator"},
        "subject": {
            "artifactId": "video:cmap",
            "revisionId": "cmap-r0001",
            "contentSha256": SHA,
        },
        "checkpoint": "cut-proof",
        "candidateSha256": SHA,
        "dependencyHashes": {"cmap": SHA},
        "dependencyLockSha256": SHA,
        "scope": "full-cut",
        "reason": "approved",
        "evidenceBundleSha256": SHA,
    }
    return body


def pipeline_run() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "runId": "run-0001",
        "videoId": "video",
        "provider": "bishop",
        "projectPath": "avo.project.json",
        "mainState": "intake",
        "sideState": None,
        "activeRefs": {},
        "blockers": [],
        "transitionHistory": [],
        "origin": {"command": "pipeline", "mode": "Owns"},
        "createdAt": "2026-08-13T12:00:00Z",
        "updatedAt": "2026-08-13T12:00:00Z",
    }


@pytest.mark.parametrize(
    ("schema,value"),
    [
        ("avo.timeline-index.schema.json", index_document()),
        ("avo.timeline-revision.schema.json", revision_document()),
        ("avo.timeline-event.schema.json", approval_event()),
        ("avo.pipeline-run.schema.json", pipeline_run()),
    ],
)
def test_runtime_documents_validate(schema: str, value: dict) -> None:
    assert validate_document(value, schema) == value


@pytest.mark.parametrize(
    ("schema,value"),
    [
        ("avo.timeline-index.schema.json", index_document()),
        ("avo.timeline-revision.schema.json", revision_document()),
        ("avo.timeline-event.schema.json", approval_event()),
        ("avo.pipeline-run.schema.json", pipeline_run()),
    ],
)
def test_runtime_documents_reject_unknown_fields(schema: str, value: dict) -> None:
    value = deepcopy(value)
    value["surprise"] = True
    with pytest.raises(ContractError):
        validate_document(value, schema)


def test_unbound_approval_is_rejected() -> None:
    event = approval_event()
    del event["candidateSha256"]
    with pytest.raises(ContractError):
        validate_document(event, "avo.timeline-event.schema.json")


def test_bad_hash_is_rejected() -> None:
    event = approval_event()
    event["candidateSha256"] = "not-a-hash"
    with pytest.raises(ContractError):
        validate_document(event, "avo.timeline-event.schema.json")
