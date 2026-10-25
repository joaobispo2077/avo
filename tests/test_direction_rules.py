"""Independent support is established from eligible records, never vote counts."""

import hashlib
from copy import deepcopy

import pytest

from avo.direction.rules import DirectionError, validate_statement


def evidence(identifier="e1", project="p1", lineage="d1"):
    excerpt = "The final comparison used readable progressive visual support."
    return {
        "evidenceId": identifier,
        "sourceProjectId": project,
        "entryId": f"entry-{identifier}",
        "documentRef": {
            "path": f"learndowns/{identifier}/learndown.json",
            "byteHash": "a" * 64,
            "role": "decision",
        },
        "selector": {"kind": "json-pointer", "pointer": "/decisions/0"},
        "excerpt": excerpt,
        "excerptHash": hashlib.sha256(excerpt.encode()).hexdigest(),
        "normalizationVersion": "1.0.0",
        "decisionLineageId": lineage,
        "normalizedState": "executed",
        "rationaleKind": "agent-inferred",
        "useEvidence": {
            "id": f"use-{identifier}",
            "documentHash": "b" * 64,
            "path": f"learndowns/{identifier}/use.json",
        },
        "approvalEvidence": None,
        "applicability": {"formats": ["analysis-review"], "sections": ["comparison"]},
    }


def statement():
    return {
        "statementId": "readable-support",
        "lineageId": "readable-support",
        "dimension": "visual-support",
        "text": "Reveal supporting comparisons progressively.",
        "rationaleKind": "agent-inferred",
        "basis": "recurring-choice",
        "kind": "artistic-preference",
        "applicability": {"formats": ["analysis-review"], "sections": ["comparison"]},
        "exclusions": ["Not a fixed graphic density"],
        "evidenceIds": ["e1", "e2"],
        "independentProjectIds": ["p1", "p2"],
    }


def records():
    return {"e1": evidence(), "e2": evidence("e2", "p2", "d2")}


def test_two_applicable_independent_actual_uses_support_recurrence_without_approval():
    validate_statement(statement(), records())


@pytest.mark.parametrize(
    "change",
    [
        "same-project",
        "same-lineage",
        "unknown-project",
        "unknown-use",
        "rejected",
        "superseded",
        "unknown-state",
    ],
)
def test_duplicate_unknown_rejected_or_superseded_records_do_not_supply_recurrence(
    change,
):
    evidence_by_id = records()
    second = evidence_by_id["e2"]
    if change == "same-project":
        second["sourceProjectId"] = "p1"
    elif change == "same-lineage":
        second["decisionLineageId"] = "d1"
    elif change == "unknown-project":
        second["sourceProjectId"] = None
    elif change == "unknown-use":
        second["useEvidence"] = None
    else:
        second["normalizedState"] = change.removesuffix("-state")
    with pytest.raises(DirectionError):
        validate_statement(statement(), evidence_by_id)


def test_reported_final_status_is_not_actual_use_or_provider_approval():
    evidence_by_id = records()
    for record in evidence_by_id.values():
        record.update(
            reportedState="final", normalizedState="unknown", useEvidence=None
        )
    with pytest.raises(DirectionError):
        validate_statement(statement(), evidence_by_id)


def test_caller_cannot_invent_evidence_or_independent_projects():
    for field, value in [
        ("evidenceIds", ["made-up"]),
        ("independentProjectIds", ["p1", "p2", "p3"]),
    ]:
        candidate = statement()
        candidate[field] = value
        with pytest.raises(DirectionError):
            validate_statement(candidate, records())


def test_changed_excerpt_cannot_keep_the_old_record_hash():
    evidence_by_id = records()
    evidence_by_id["e1"]["excerpt"] = "A different claim."
    with pytest.raises(DirectionError):
        validate_statement(statement(), evidence_by_id)


def test_one_project_can_inform_a_tentative_statement_without_becoming_recurrent():
    candidate = statement()
    candidate.update(
        basis="tentative-inference", evidenceIds=["e1"], independentProjectIds=["p1"]
    )
    validate_statement(candidate, {"e1": evidence()})


def test_explicit_creator_instruction_is_distinct_from_agent_inference():
    candidate = statement()
    candidate.update(
        basis="creator-instruction",
        rationaleKind="creator-recorded",
        evidenceIds=["e1"],
        independentProjectIds=["p1"],
    )
    record = evidence()
    with pytest.raises(DirectionError):
        validate_statement(candidate, {"e1": record})
    record.update(
        rationaleKind="creator-recorded",
        explicitInstruction={
            "source": "creator:instruction-1",
            "text": "Use progressive comparisons for my analysis videos.",
        },
    )
    validate_statement(candidate, {"e1": record})


def test_recorded_rationale_cannot_be_claimed_from_unknown_or_inferred_source():
    candidate = statement()
    candidate["rationaleKind"] = "creator-recorded"
    with pytest.raises(DirectionError):
        validate_statement(candidate, records())


def test_source_applicability_cannot_be_broadened_into_a_different_format():
    candidate = statement()
    candidate["applicability"]["formats"] = ["focused-short"]
    with pytest.raises(DirectionError):
        validate_statement(candidate, records())


def test_validation_preserves_tentative_basis_without_rewriting_evidence():
    candidate = statement()
    candidate.update(basis="tentative-inference", rationaleKind="unknown")
    evidence_by_id = records()
    before = deepcopy(evidence_by_id)
    validate_statement(candidate, evidence_by_id)
    assert evidence_by_id == before
    assert candidate["basis"] == "tentative-inference"


@pytest.mark.parametrize("target", ["statement", "applicability"])
def test_source_exclusions_cannot_be_lost_when_a_preference_is_synthesized(target):
    candidate = statement()
    evidence_by_id = records()
    excluded = "Exclude music-led performance videos."
    evidence_by_id["e1"]["applicability"]["exclusions"] = [excluded]
    with pytest.raises(DirectionError) as error:
        validate_statement(candidate, evidence_by_id)
    assert error.value.code == "DIR_APPROVAL_SCOPE"
    if target == "statement":
        candidate["exclusions"].append(excluded)
    else:
        candidate["applicability"]["exclusions"] = [excluded]
    validate_statement(candidate, evidence_by_id)
