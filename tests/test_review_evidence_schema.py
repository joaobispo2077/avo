from __future__ import annotations

import copy
import unittest

from avo.timeline.contracts import ContractError, validate_document


def valid_manifest() -> dict:
    dependencies = {"cmap": "b" * 64, "cutOutput": "c" * 64, "sync-map": "1" * 64}
    return {
        "schemaVersion": "1.0.0",
        "checkpoint": "cut-proof",
        "candidate": {
            "sha256": "a" * 64,
            "byteSize": 42,
            "path": "proof.mp4",
            "dependencies": dependencies,
            "renderProfile": "proof-360p",
            "identityHash": "d" * 64,
        },
        "dependencyLockSha256": "e" * 64,
        "changeSummary": {
            "headline": "CMap revision trims one idle pause",
            "items": [{
                "artifactType": "cmap",
                "revisionId": "cmap-r0001",
                "reason": "remove idle pause",
                "operationCounts": {"replace": 1},
                "targets": ["segment-one"],
                "truncatedTargets": 0,
            }],
            "windows": [],
            "staleDependencies": [],
        },
        "state": "ai-passed",
        "evidence": [
            {
                "evidenceId": "watch-001",
                "kind": "watch",
                "tool": {"name": "watch-skill", "version": "1", "model": "vision"},
                "runAt": "2026-08-13T00:00:00Z",
                "candidateHash": "a" * 64,
                "candidateIdentityHash": "d" * 64,
                "dependencyLockSha256": "e" * 64,
                "dependencyHashes": dependencies,
                "scope": {"mode": "full", "windows": [], "rationale": "cut proof"},
                "coverage": {
                    "durationSeconds": 10,
                    "reviewedSeconds": 10,
                    "requiredWindows": 0,
                    "reviewedWindows": 0,
                },
                "status": "pass",
                "findings": [],
                "artifacts": [{"path": "watch.json", "sha256": "f" * 64}],
                "attempt": 1,
            }
        ],
        "attempts": [],
        "unresolvedRisks": [],
        "approval": None,
    }


class ReviewSchemaTests(unittest.TestCase):
    def test_candidate_bound_evidence_valid(self):
        validate_document(valid_manifest(), "avo.review-evidence.schema.json")

    def test_unbound_evidence_rejected(self):
        document = valid_manifest()
        document["evidence"] = []
        with self.assertRaises(ContractError):
            validate_document(document, "avo.review-evidence.schema.json")

    def test_n_a_requires_policy_rationale_actor_and_basis(self):
        document = valid_manifest()
        document["evidence"][0]["status"] = "not-applicable"
        with self.assertRaises(ContractError):
            validate_document(document, "avo.review-evidence.schema.json")
        document["evidence"][0]["notApplicable"] = {
            "policy": "sync-risk-v1",
            "rationale": "single embedded clock",
            "actor": {"type": "agent", "id": "avo"},
            "basisSha256": "1" * 64,
        }
        validate_document(document, "avo.review-evidence.schema.json")

    def test_unhashed_artifact_and_insufficient_coverage_rejected(self):
        for mutation in ("artifact", "coverage"):
            document = copy.deepcopy(valid_manifest())
            if mutation == "artifact":
                del document["evidence"][0]["artifacts"][0]["sha256"]
            else:
                document["evidence"][0]["scope"]["mode"] = "windows"
                document["evidence"][0]["scope"]["windows"] = []
            with self.assertRaises(ContractError):
                validate_document(document, "avo.review-evidence.schema.json")
