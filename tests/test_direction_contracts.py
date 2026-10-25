"""Neutral contracts for provider evidence, proposals and creator decisions.

These tests intentionally fail until the feature's direction schema exists.
Invalid-input cases validate a positive counterpart first, so a missing schema
cannot be mistaken for successful rejection of unsafe input.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from avo.timeline.contracts import (
    ContractError,
    document_hash_excluding,
    load_schema,
    validate_document,
)

FIXTURES = Path(__file__).parent / "fixtures" / "direction"
SCHEMA = "avo.direction.schema.json"
SHA = "a" * 64
DIMENSIONS = (
    "editorial-voice",
    "creator-presence",
    "emotional-arc",
    "pacing",
    "visual-support",
    "motion",
    "evidence-inserts",
    "sound",
    "captions",
    "color",
    "avoidance",
)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _envelope(kind: str, **fields: object) -> dict:
    result = {
        "schemaVersion": "1.0.0",
        "documentType": kind,
        "id": f"neutral-{kind.lower()}",
        "createdAt": "2026-01-04T12:00:00Z",
        "createdBy": {"type": "native", "id": "avo.direction"},
        **fields,
    }
    result["documentHash"] = document_hash_excluding(result, "documentHash")
    return result


def _ref(document: dict, path: str) -> dict:
    return {
        "id": document["id"],
        "documentHash": document["documentHash"],
        "path": path,
    }


def _provenance() -> dict:
    return {
        "executionKind": "driving-agent",
        "agentId": "fixture-agent",
        "modelId": None,
        "packetHash": SHA,
        "promptHash": SHA,
    }


def evidence_record() -> dict:
    legacy_bytes = (FIXTURES / "legacy.json").read_bytes()
    summary = _fixture("legacy.json")["summary"]
    return {
        "evidenceId": "neutral-evidence-001",
        "sourceProjectId": "neutral-project-001",
        "entryId": "20260101-neutral-tutorial",
        "documentRef": {
            "path": "learndowns/20260101-neutral-tutorial/learndown.json",
            "byteHash": hashlib.sha256(legacy_bytes).hexdigest(),
            "role": "legacy-summary",
        },
        "selector": {"kind": "json-pointer", "pointer": "/summary"},
        "excerpt": summary,
        "excerptHash": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
        "normalizationVersion": "1.0.0",
        "decisionLineageId": "neutral-decision-001",
        "reportedState": "final",
        "normalizedState": "unknown",
        "useEvidence": None,
        "approvalEvidence": None,
        "applicability": {
            "formats": ["step-by-step"],
            "sections": ["demonstration"],
            "conditions": [],
            "exclusions": [],
        },
        "rationaleKind": "unknown",
        "interpretation": "The recorded demonstration prioritizes intelligible speech.",
    }


def source_manifest() -> dict:
    record = evidence_record()
    return _envelope(
        "SourceManifest",
        provider="neutral",
        collectionId="neutral-collection-001",
        entries=[
            {
                "entryId": record["entryId"],
                "layout": "legacy-narrative",
                "disposition": "included",
                "reason": "The bounded legacy summary is available.",
                "completionEvidence": {
                    "catalogStatus": "final",
                    "snapshotStatus": None,
                    "observedFacts": ["legacy-summary-present"],
                },
                "sourceProjectId": record["sourceProjectId"],
                "identityBasis": "explicit-project-provenance",
                "identityUncertainty": [],
                "derivativeContext": None,
                "relatedEntryIds": [],
                "decisionLineageIds": [record["decisionLineageId"]],
                "documents": [
                    {
                        **record["documentRef"],
                        "sizeBytes": (FIXTURES / "legacy.json").stat().st_size,
                        "consumedSelectors": [record["selector"]],
                        "inspectedAt": "2026-01-04T12:00:00Z",
                    }
                ],
                "catalogEvidence": None,
                "recordedMasterIdentity": None,
            }
        ],
        evidenceRecords=[record],
        coverage={
            "discovered": 1,
            "included": 1,
            "related": 0,
            "excluded": 0,
            "unavailable": 0,
            "oversize": 0,
            "distinctProjects": 1,
            "unknownDimensions": list(DIMENSIONS),
        },
        sourceSetHash=SHA,
        semanticEvidenceHash=SHA,
        limits={"documentBytes": 2097152, "collectionBytes": 16777216},
        partialReasons=[],
    )


def statement() -> dict:
    return {
        "statementId": "neutral-statement-001",
        "lineageId": "neutral-statement-lineage-001",
        "dimension": "sound",
        "text": "Prioritize intelligible speech during demonstrations.",
        "rationale": "This is a tentative interpretation of one project's report.",
        "rationaleKind": "agent-inferred",
        "basis": "tentative-inference",
        "kind": "artistic-preference",
        "applicability": evidence_record()["applicability"],
        "exclusions": ["Music-led performance"],
        "evidenceIds": ["neutral-evidence-001"],
        "independentProjectIds": ["neutral-project-001"],
        "contradictions": [],
        "unknowns": ["The creator's stated rationale is unavailable."],
        "historicalExamples": [],
        "creatorDispositionRef": None,
    }


def provider_packet() -> dict:
    manifest = source_manifest()
    return _envelope(
        "ProviderInputPacket",
        provider="neutral",
        profileId="editorial",
        parentRef=None,
        sourceManifestRef=_ref(manifest, "collections/neutral-manifest.json"),
        sourceSetHash=manifest["sourceSetHash"],
        brandGuideRef=None,
        statementLineages=[],
        evidenceRecords=manifest["evidenceRecords"],
        coverage=manifest["coverage"],
        limits={"packetWords": 24000},
        submissionTemplateVersion="1.0.0",
        expectedIndexHash="absent",
    )


def provider_proposal_request() -> dict:
    packet = provider_packet()
    return {
        "requestId": "neutral-propose-001",
        "packetRef": _ref(packet, "collections/neutral-packet.json"),
        "expectedIndexHash": "absent",
        "candidate": {
            "summary": "Clear speech and selective explanatory support.",
            "statements": [statement()],
            "variants": [],
            "avoidances": [],
            "dimensionCoverage": {name: "unknown" for name in DIMENSIONS},
            "changeSummary": "Initial tentative proposal.",
        },
        "synthesisProvenance": _provenance(),
    }


def provider_decision_request() -> dict:
    return {
        "requestId": "neutral-decision-request-001",
        "targetRef": {
            "id": "neutral-profile-001",
            "documentHash": SHA,
            "path": "profiles/editorial/r0001.json",
        },
        "expectedIndexHash": SHA,
        "action": "accept",
        "scope": "provider",
        "actor": {"type": "human", "id": "creator-1"},
        "reason": "The creator accepted this exact tentative direction.",
        "humanInstruction": {
            "source": "session:message-1",
            "text": "Accept this exact provider proposal.",
        },
    }


def _validate(kind: str, value: dict) -> None:
    validate_document(value, f"{SCHEMA}#/$defs/{kind}")


def test_neutral_legacy_and_catalog_keep_context_without_false_authority():
    legacy = _fixture("legacy.json")
    catalog = _fixture("catalog.json")
    assert legacy["schemaVersion"] == 1
    assert legacy["provider"] == catalog["provider"] == "neutral"
    assert catalog["baseEntryId"] != catalog["entryId"]
    assert catalog["newProjectApprovalsInherited"] is False
    assert catalog["publishingAuthorizationInherited"] is False


def test_native_snapshot_fixture_is_valid_and_hash_is_not_just_declared():
    snapshot = _fixture("snapshot.json")
    validate_document(snapshot, "avo.timeline-learning.schema.json")
    assert snapshot["snapshotHash"] == document_hash_excluding(snapshot, "snapshotHash")
    assert snapshot["decisionOutcomes"][0]["recurrence"] == 9
    assert snapshot["decisionOutcomes"][0]["status"] == "active"
    assert snapshot["decisionOutcomes"][1]["status"] == "superseded"


@pytest.mark.parametrize(
    ("kind", "factory"),
    [
        ("EvidenceRecord", evidence_record),
        ("DirectionStatement", statement),
        ("SourceManifest", source_manifest),
        ("ProviderInputPacket", provider_packet),
        ("ProviderProposeRequest", provider_proposal_request),
        ("ProviderDecideRequest", provider_decision_request),
    ],
)
def test_positive_provider_contracts(kind, factory):
    _validate(kind, factory())


@pytest.mark.parametrize(
    ("kind", "factory", "field"),
    [
        ("SourceManifest", source_manifest, "masterApproved"),
        ("ProviderInputPacket", provider_packet, "resultingIndexHash"),
        ("ProviderProposeRequest", provider_proposal_request, "renderCommand"),
        ("ProviderDecideRequest", provider_decision_request, "acceptMaster"),
    ],
)
def test_unknown_fields_cannot_smuggle_authority_or_future_hashes(kind, factory, field):
    good = factory()
    _validate(kind, good)
    unsafe = {**good, field: "not-authorized"}
    with pytest.raises(ContractError):
        _validate(kind, unsafe)


@pytest.mark.parametrize("field", ["actor", "reason", "humanInstruction"])
def test_provider_decision_requires_actual_instruction_fields(field):
    request = provider_decision_request()
    _validate("ProviderDecideRequest", request)
    del request[field]
    with pytest.raises(ContractError):
        _validate("ProviderDecideRequest", request)


@pytest.mark.parametrize("scope", ["project", "master", "global"])
def test_provider_decision_cannot_represent_another_approval_scope(scope):
    request = provider_decision_request()
    _validate("ProviderDecideRequest", request)
    request["scope"] = scope
    with pytest.raises(ContractError):
        _validate("ProviderDecideRequest", request)


@pytest.mark.parametrize("bad_hash", ["A" * 64, "0" * 63, "not-a-hash"])
def test_packet_refs_require_exact_lowercase_sha256(bad_hash):
    request = provider_proposal_request()
    _validate("ProviderProposeRequest", request)
    request["packetRef"]["documentHash"] = bad_hash
    with pytest.raises(ContractError):
        _validate("ProviderProposeRequest", request)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("normalizedState", "approved-because-master-final"),
        ("rationaleKind", "creator-assumed"),
        ("excerpt", "x" * 1001),
    ],
)
def test_evidence_does_not_accept_invented_states_or_unbounded_excerpt(field, value):
    record = evidence_record()
    _validate("EvidenceRecord", record)
    record[field] = value
    with pytest.raises(ContractError):
        _validate("EvidenceRecord", record)


def test_document_type_is_specific_and_not_a_generic_arbitrary_payload():
    packet = provider_packet()
    _validate("ProviderInputPacket", packet)
    packet["documentType"] = "ApprovedMaster"
    with pytest.raises(ContractError):
        _validate("ProviderInputPacket", packet)


def test_direction_schema_is_strict_local_draft_2020_12():
    schema = load_schema(SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    for name in (
        "SourceManifest",
        "ProviderInputPacket",
        "DirectionStatement",
        "EvidenceRecord",
        "ProviderProfileVersion",
        "ProviderIndex",
        "CreatorDecision",
        "RefreshReport",
        "BuiltinDirection",
        "ProviderProposeRequest",
        "ProviderDecideRequest",
    ):
        definition = schema["$defs"][name]
        assert definition.get("additionalProperties") is False, name
    text = json.dumps(schema)
    assert '"$ref": "http:' not in text
    assert '"$ref": "https:' not in text


def test_request_dto_does_not_accept_native_envelope_or_false_actor():
    request = provider_decision_request()
    _validate("ProviderDecideRequest", request)
    for key, value in (
        ("documentHash", SHA),
        ("createdBy", {"type": "native", "id": "avo.direction"}),
        ("actor", {"type": "agent", "id": "model"}),
    ):
        changed = copy.deepcopy(request)
        changed[key] = value
        with pytest.raises(ContractError):
            _validate("ProviderDecideRequest", changed)
