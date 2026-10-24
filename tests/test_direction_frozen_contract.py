"""Frozen artistic inputs are typed snapshots, never render sources."""

import pytest

from avo.timeline.contracts import ContractError, validate_document

SCHEMA = "avo.briefstart.schema.json#/$defs/FrozenBriefSource"


def valid_snapshot():
    from tests.test_briefstart_contracts import reference

    return {
        "schemaVersion": "1.0.0",
        "documentType": "FrozenBriefSource",
        "id": "frozen-one",
        "createdAt": "2026-10-16T12:00:00Z",
        "createdBy": {"type": "native", "id": "avo.direction"},
        "documentHash": "a" * 64,
        "provider": "neutral",
        "videoId": "next",
        "source": {
            "id": "prior-natural-delivery",
            "kind": "reference",
            "document": reference(),
            "disposition": "user-described",
        },
    }


def test_frozen_input_uses_typed_source_body_without_rewriting_it():
    value = valid_snapshot()
    validate_document(value, SCHEMA)
    assert "documentType" not in value["source"]["document"]


def test_frozen_input_cannot_grant_media_or_master_authority():
    value = valid_snapshot()
    value["source"]["document"]["approvedMaster"] = True
    with pytest.raises(ContractError):
        validate_document(value, SCHEMA)
