"""Briefstart trust contracts, independent of models and private media.

These are schema-level cases. Native exact-content, publication and human-scope
checks belong to the later service tests; an accepted schema is not approval.
"""

import json
from pathlib import Path

import pytest

from avo.timeline.contracts import ContractError, validate_document

FIXTURES = Path(__file__).parent / "fixtures" / "briefstart"
SCHEMA = "avo.briefstart.schema.json#/$defs/"
HASH = "a" * 64


def validate(kind, document):
    return validate_document(document, SCHEMA + kind)


def reference():
    return {
        "schemaVersion": "1.0.0",
        "referenceId": "prior-natural-delivery",
        "label": "A creator-selected earlier analysis",
        "locator": None,
        "selectedAspects": ["Natural cadence", "Selective explanatory graphics"],
        "description": "Use the delivery as a reference, not its music or timings.",
        "observationKind": "user-described",
        "applicability": ["analysis-review"],
        "exclusions": ["No transfer of media rights or approval"],
        "knownUsageLimits": "Artistic reference only.",
    }


def document_ref():
    return {"id": "packet-1", "documentHash": HASH, "path": "inputs/packet-1.json"}


def propose_request():
    def option(identifier, rhythm, visual):
        return {
            "id": identifier,
            "approach": "Compare the same argument with a distinct presentation emphasis.",
            "treatment": {
                "rhythm": rhythm,
                "visual": visual,
                "motion": "Selective support with readable holds.",
                "sound": "Speech leads and purposeful sounds remain below it.",
            },
            "fit": "Keeps the promise of a qualified comparison.",
            "tradeoffs": [
                "The chosen emphasis changes how much screen evidence is needed."
            ],
            "sourceContribution": [
                {"sourceId": "editorial-r0001", "aspects": ["Natural cadence"]}
            ],
            "statementIds": ["natural-cadence"],
            "exclusions": ["No transferred music or timing settings"],
        }

    return {
        "requestId": "proposal-1",
        "packetRef": document_ref(),
        "expectedIndexHash": "absent",
        "options": [
            option("restrained", "Conversational", "Presenter with selected evidence"),
            option("comparison", "Progressive comparison", "Side-by-side explanations"),
        ],
        "shortView": "Choose a conversational comparison or a more visual progressive comparison.",
        "synthesisProvenance": {
            "executionKind": "driving-agent",
            "agentId": "fixture-agent",
            "modelId": None,
            "packetHash": HASH,
            "promptHash": HASH,
        },
    }


def decide_request():
    return {
        "requestId": "selection-1",
        "targetRef": {
            "id": "brief-1",
            "documentHash": HASH,
            "path": "briefs/brief-1.json",
        },
        "expectedIndexHash": "b" * 64,
        "action": "select",
        "scope": "project",
        "actor": {"type": "human", "id": "creator-1"},
        "reason": "Choose a quieter comparison for this video.",
        "humanInstruction": {
            "source": "session:message-1",
            "text": "Choose the restrained option for this project.",
        },
        "optionId": "restrained",
    }


def test_context_input_is_valid_without_native_identity_or_approval():
    context = json.loads((FIXTURES / "context.json").read_text(encoding="utf-8"))
    assert validate("Context", context) == context
    assert "documentHash" not in context


def test_reference_input_preserves_user_description_and_unavailable_locator():
    value = reference()
    assert validate("ReferenceDescriptor", value) == value
    assert value["observationKind"] == "user-described"
    assert value["locator"] is None


@pytest.mark.parametrize(
    "kind,factory", [("Context", None), ("ReferenceDescriptor", reference)]
)
@pytest.mark.parametrize(
    "key", ["masterApproved", "execute", "modelEndpoint", "renderSettings"]
)
def test_context_and_reference_reject_authority_or_execution_fields(kind, factory, key):
    value = (
        factory()
        if factory
        else json.loads((FIXTURES / "context.json").read_text(encoding="utf-8"))
    )
    value[key] = True
    with pytest.raises(ContractError):
        validate(kind, value)


def test_reference_cannot_claim_unrecognized_inspection_status():
    value = reference()
    value["observationKind"] = "watched-because-url-exists"
    with pytest.raises(ContractError):
        validate("ReferenceDescriptor", value)


def test_reference_requires_selected_aspects_and_attribution_limits():
    for missing in (
        "referenceId",
        "selectedAspects",
        "observationKind",
        "knownUsageLimits",
    ):
        value = reference()
        del value[missing]
        with pytest.raises(ContractError):
            validate("ReferenceDescriptor", value)


def test_decision_request_has_exact_target_and_explicit_project_human_instruction():
    value = decide_request()
    assert validate("BriefDecideRequest", value) == value


def test_proposal_input_carries_structured_options_without_native_approval():
    value = propose_request()
    assert validate("BriefProposeRequest", value) == value


@pytest.mark.parametrize("location", ["treatment", "sourceContribution"])
def test_option_cannot_smuggle_execution_or_approval_into_nested_fields(location):
    value = propose_request()
    option = value["options"][0]
    target = (
        option[location][0] if location == "sourceContribution" else option[location]
    )
    target["execute"] = "render-a-master"
    with pytest.raises(ContractError):
        validate("BriefProposeRequest", value)


@pytest.mark.parametrize(
    "missing",
    [
        "requestId",
        "targetRef",
        "expectedIndexHash",
        "actor",
        "reason",
        "humanInstruction",
    ],
)
def test_decision_cannot_be_selected_from_incomplete_or_implicit_authority(missing):
    value = decide_request()
    del value[missing]
    with pytest.raises(ContractError):
        validate("BriefDecideRequest", value)


@pytest.mark.parametrize(
    "field,value", [("documentHash", "latest"), ("id", ""), ("path", "")]
)
def test_decision_target_requires_an_exact_nonempty_reference(field, value):
    request = decide_request()
    request["targetRef"][field] = value
    with pytest.raises(ContractError):
        validate("BriefDecideRequest", request)


@pytest.mark.parametrize(
    "actor", [{"type": "agent", "id": "helper"}, {"type": "human"}]
)
def test_automated_identity_cannot_be_a_creator_decision(actor):
    value = decide_request()
    value["actor"] = actor
    with pytest.raises(ContractError):
        validate("BriefDecideRequest", value)


@pytest.mark.parametrize(
    "instruction", [{"source": "", "text": "Yes"}, {"source": "session:1", "text": ""}]
)
def test_empty_human_instruction_is_not_approval(instruction):
    value = decide_request()
    value["humanInstruction"] = instruction
    with pytest.raises(ContractError):
        validate("BriefDecideRequest", value)


def test_project_decision_cannot_accept_a_provider_profile():
    value = decide_request()
    value["scope"] = "provider"
    with pytest.raises(ContractError):
        validate("BriefDecideRequest", value)


@pytest.mark.parametrize("kind", ["BriefProposeRequest", "BriefDecideRequest"])
def test_request_dto_cannot_supply_native_envelope_or_inherited_approval(kind):
    factory = propose_request if kind == "BriefProposeRequest" else decide_request
    for key in ("documentHash", "createdAt", "documentType", "approved"):
        value = factory()
        value[key] = True
        with pytest.raises(ContractError):
            validate(kind, value)


@pytest.mark.parametrize(
    "kind",
    [
        "BriefInputPacket",
        "ProjectBriefVersion",
        "BriefSelection",
        "ProjectBriefIndex",
        "BriefOptOutProposal",
        "StageGuidanceReceipt",
    ],
)
def test_stored_authority_is_not_an_unsealed_input_dictionary(kind):
    with pytest.raises(ContractError):
        validate(kind, {"provider": "neutral-channel", "videoId": "next-analysis"})


def test_opt_out_cannot_be_forged_as_an_ordinary_choice_or_approval():
    with pytest.raises(ContractError):
        validate(
            "BriefOptOutProposal",
            {
                "documentType": "BriefOptOutProposal",
                "selector": "none",
                "previousSelectionRef": document_ref(),
                "approved": True,
            },
        )


def test_neutral_accepted_fixture_keeps_acceptance_separate_from_profile_content():
    fixture = json.loads(
        (FIXTURES / "accepted-profile.json").read_text(encoding="utf-8")
    )
    assert fixture["provider"] == "neutral-channel"
    assert fixture["acceptanceRef"]["id"] != fixture["profileRef"]["id"]
    assert (
        fixture["acceptanceRef"]["documentHash"]
        != fixture["profileRef"]["documentHash"]
    )
    assert "approved" not in fixture
    assert "bishop" not in json.dumps(fixture).lower()
