from __future__ import annotations

import pytest

from avo.timeline.contracts import ContractError, content_hash, validate_document


def _legacy_cut() -> dict:
    body = {
        "schemaVersion": "1.0.0",
        "kind": "cut-proof",
        "materializationId": "cut-proof-cmap-r0001-aaaaaaaaaaaa",
        "cmapRevisionId": "cmap-r0001",
        "canonicalInputLock": {"cmapRevisionHash": "c" * 64},
        "renderProfile": "draft",
        "projectionHash": "1" * 64,
        "output": {"sha256": "2" * 64, "sizeBytes": 10, "locator": "proof.mp4"},
        "producer": {"name": "fixture", "version": "1"},
        "createdAt": "2026-08-14T00:00:00Z",
    }
    return {**body, "materializationHash": content_hash(body)}


def _assembly() -> dict:
    lock = {
        "cmapRevisionId": "cmap-r0001",
        "cmapRevisionHash": "a" * 64,
        "syncRevisionId": "sync-r0001",
        "syncRevisionHash": "b" * 64,
        "bmapRevisionId": "bmap-r0001",
        "bmapRevisionHash": "c" * 64,
        "tracksRevisionId": "tracks-r0001",
        "tracksRevisionHash": "d" * 64,
        "rawFingerprints": {"camera-a": "e" * 64},
    }
    contract = {
        "width": 1920,
        "height": 1080,
        "frameRate": {"num": 30000, "den": 1001, "tolerance": 0.001},
        "allowedTransformations": ["trim", "concat", "encode"],
    }
    policy_body = {
        "policyId": "avo.delivery-fidelity",
        "profileId": "fixture-1080p",
        "settingSources": {"profileId": "project"},
        "renderContract": contract,
        "prohibitedBaseClasses": ["proof", "proxy"],
        "roleRules": {},
    }
    policy = {**policy_body, "policyHash": content_hash(policy_body)}
    lineage_body = {
        "schemaVersion": "1.0.0",
        "canonicalInputLock": lock,
        "projectionHash": "f" * 64,
        "nodes": [
            {
                "nodeId": "source-a",
                "kind": "source",
                "role": "base",
                "mediaClass": "camera-original",
                "locator": "camera-a.mov",
                "sha256": "e" * 64,
                "pictureCarrying": True,
                "media": {"width": 1920, "height": 1080},
            },
            {
                "nodeId": "output",
                "kind": "output",
                "role": "output",
                "mediaClass": "rendered-output",
                "locator": "master.mp4",
                "sha256": "1" * 64,
                "pictureCarrying": True,
                "media": {"width": 1920, "height": 1080},
            },
        ],
        "edges": [
            {
                "edgeId": "edge-0001",
                "from": "source-a",
                "to": "output",
                "operation": "encode",
                "order": 0,
                "parameters": {},
            }
        ],
        "rootIds": ["output"],
    }
    lineage = {
        **lineage_body,
        "pictureLineageHash": content_hash(lineage_body),
    }
    body = {
        "schemaVersion": "1.1.0",
        "kind": "assembly",
        "materializationId": "assembly-fixture",
        "canonicalInputLock": lock,
        "projectionHash": "f" * 64,
        "renderProfile": "delivery",
        "renderContract": contract,
        "renderContractHash": content_hash(contract),
        "renderHash": "2" * 64,
        "pictureLineage": lineage,
        "pictureLineageHash": lineage["pictureLineageHash"],
        "deliveryFidelityPolicy": policy,
        "deliveryFidelityPolicyHash": policy["policyHash"],
        "output": {"sha256": "1" * 64, "sizeBytes": 10, "locator": "master.mp4"},
        "producer": {"name": "fixture", "version": "1"},
        "createdAt": "2026-08-14T00:00:00Z",
    }
    return {**body, "materializationHash": content_hash(body)}


def test_legacy_cut_proof_remains_readable():
    validate_document(_legacy_cut(), "avo.materialization.schema.json")


def test_assembly_requires_complete_strict_lineage_and_policy():
    assembly = _assembly()
    validate_document(assembly, "avo.materialization.schema.json")
    assembly.pop("pictureLineageHash")
    with pytest.raises(ContractError):
        validate_document(assembly, "avo.materialization.schema.json")


def test_unknown_assembly_fields_are_rejected():
    document = _assembly()
    document["unknown"] = True
    with pytest.raises(ContractError):
        validate_document(document, "avo.materialization.schema.json")
