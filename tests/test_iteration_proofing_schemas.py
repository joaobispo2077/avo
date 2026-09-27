from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from avo.paths import schemas_dir
from tests.jsonschema_support import validator_for

SHA = "a" * 64
NEW_SCHEMAS = (
    "avo.iteration-ledger.schema.json",
    "avo.proof-plan.schema.json",
    "avo.generated-asset.schema.json",
    "avo.component-instance.schema.json",
    "avo.candidate-snapshot.schema.json",
    "avo.still-extraction.schema.json",
    "avo.timeline-learning.schema.json",
    "avo.vision-review-plan.schema.json",
    "avo.vision-finding.schema.json",
)


def _schema(name: str) -> dict:
    return json.loads((schemas_dir() / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", NEW_SCHEMAS)
def test_new_iteration_proofing_schema_is_registered_and_well_formed(name: str) -> None:
    schema = _schema(name)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith(name)
    assert schema.get("additionalProperties") is False


def test_iteration_ledger_exposes_strict_foundation_entities() -> None:
    schema = _schema("avo.iteration-ledger.schema.json")
    for name in (
        "iterationRecord",
        "decisionLedgerEntry",
        "reworkClassification",
        "regressionContract",
    ):
        assert schema["$defs"][name]["additionalProperties"] is False

    rework = {
        "reworkId": "rework-001",
        "iterationId": "iteration-001",
        "reworkGroupId": "group-001",
        "origin": "implementation-defect",
        "summary": "Audio join clipped a protected word.",
        "impact": {"affectedArtifacts": ["tracks"], "programWindows": []},
        "evidenceRefs": [{"evidenceId": "audio-qc-001", "sha256": SHA}],
        "confidence": 0.9,
        "capabilityGap": None,
        "supersedes": None,
        "classifiedBy": {"type": "agent", "id": "avo"},
    }
    validator = validator_for(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            **schema["$defs"]["reworkClassification"],
        }
    )
    assert list(validator.iter_errors(rework)) == []
    rework["surprise"] = True
    assert list(validator.iter_errors(rework))


def test_candidate_snapshot_enforces_lifecycle_evidence() -> None:
    schema = _schema("avo.candidate-snapshot.schema.json")
    candidate = {
        "schemaVersion": "1.0.0",
        "snapshotId": "snapshot-001",
        "candidate": {"sha256": SHA, "sizeBytes": 10, "locator": "proof.mp4"},
        "iterationId": "iteration-001",
        "proofPlan": {"artifactId": "proof-plan-001", "sha256": SHA},
        "materialization": {"artifactId": "materialization-001", "sha256": SHA},
        "transcript": None,
        "review": None,
        "regressionResult": None,
        "approval": None,
        "state": "rendered",
        "supersedesSnapshotId": None,
        "createdAt": "2026-09-27T00:00:00Z",
        "snapshotHash": SHA,
    }
    validator = validator_for(schema)
    assert list(validator.iter_errors(candidate)) == []
    candidate["state"] = "approved"
    assert list(validator.iter_errors(candidate))


def test_vision_finding_routes_material_uncertainty_to_human() -> None:
    schema = _schema("avo.vision-finding.schema.json")
    finding = {
        "schemaVersion": "1.0.0",
        "findingId": "finding-001",
        "category": "privacy",
        "severity": "warning",
        "confidence": 0.55,
        "programRange": {"startFrame": 10, "endFrameExclusive": 20},
        "evidenceRefs": [
            {"kind": "observed-frame", "artifactId": "frame-10", "sha256": SHA}
        ],
        "criterionIds": ["privacy-visible-plate"],
        "obligationIds": [],
        "observed": "A plate-like region is visible.",
        "expected": "Private identifiers are obscured.",
        "whyItMatters": "Potential privacy exposure.",
        "alternativeExplanations": ["The region may be a texture."],
        "message": "Possible visible plate requires review.",
        "suggestedAction": None,
        "requiresHuman": True,
        "status": "needs-human",
        "humanDisposition": None,
    }
    validator = validator_for(schema)
    assert list(validator.iter_errors(finding)) == []
    finding["requiresHuman"] = False
    assert list(validator.iter_errors(finding))


def test_additive_schema_extensions_are_registered_without_removing_legacy_versions() -> (
    None
):
    materialization = _schema("avo.materialization.schema.json")
    assert {item["$ref"] for item in materialization["oneOf"]} >= {
        "#/$defs/legacyCutProof",
        "#/$defs/assembly",
    }
    assert "audiovisualLineage" in materialization["$defs"]

    pipeline = _schema("avo.pipeline-run.schema.json")
    assert (
        "activeCandidateSnapshot" in pipeline["properties"]["activeRefs"]["properties"]
    )

    review = _schema("avo.review-evidence.schema.json")
    assert "regressionResult" in review["$defs"]
    assert "visionCoverageManifest" in review["$defs"]["evidence"]["properties"]

    reconstruction = _schema("avo.reconstruction-bundle.schema.json")
    for name in (
        "iterationLedgers",
        "proofPlans",
        "candidateSnapshots",
        "timelineLearning",
    ):
        assert name in reconstruction["properties"]

    learndown = _schema("avo.learndown.schema.json")
    assert learndown["properties"]["schemaVersion"]["const"] == 1
    assert "timelineLearningRef" in learndown["properties"]

    for name in ("avo.timeline-index.schema.json", "avo.timeline-revision.schema.json"):
        assert "iteration-ledger" in _schema(name)["properties"]["artifactType"]["enum"]


def test_all_new_schema_files_are_in_the_automatic_test_registry() -> None:
    directory = Path(schemas_dir())
    registered = {path.name for path in directory.glob("*.json")}
    assert set(NEW_SCHEMAS) <= registered
