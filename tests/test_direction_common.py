"""Pure direction identity, selector and visible-reading-budget contracts."""

from copy import deepcopy

import pytest

from avo.direction.rules import (
    DirectionError,
    document_ref,
    parse_selector,
    seal,
    validate,
    visible_word_count,
)
from avo.timeline.contracts import document_hash_excluding


@pytest.mark.parametrize(
    "selector,expected",
    [
        ("none", {"mode": "none", "id": None, "version": None}),
        ("references", {"mode": "references", "id": None, "version": None}),
        (
            "builtin:analysis-review@1.0.0",
            {"mode": "builtin", "id": "analysis-review", "version": "1.0.0"},
        ),
        (
            "provider:editorial@r0001",
            {"mode": "provider", "id": "editorial", "version": "r0001"},
        ),
    ],
)
def test_selector_requires_an_exact_version_and_returns_no_mutable_alias(
    selector, expected
):
    assert parse_selector(selector) == expected


@pytest.mark.parametrize(
    "selector",
    [
        None,
        "",
        "latest",
        "provider:editorial",
        "builtin:analysis@latest",
        "provider:../other@r0001",
        "none extra",
        "builtin:analysis@1.0.0 extra",
    ],
)
def test_selector_rejects_ambiguous_aliases_and_uncontained_identities(selector):
    with pytest.raises(DirectionError) as error:
        parse_selector(selector)
    assert error.value.code == "DIR_INVALID_REFERENCE"


@pytest.mark.parametrize(
    "text,count",
    [
        ("", 0),
        ("Ritmo\u00a0natural\u3000da\tfala", 4),
        ("ＡＶＯ mantém a intenção.", 4),
        (
            "# Opção 1\n\n**Ritmo** natural e [evidência legível](https://example.invalid/a/very/long/path)",
            7,
        ),
        (
            "### Quiet choice\n- Preserve `complete words`.\n- Avoid **rushed** answers.",
            8,
        ),
        ("[Example][source]\n\n[source]: https://example.invalid/document", 1),
    ],
)
def test_word_budget_counts_visible_unicode_text_and_excludes_only_markup_targets(
    text, count
):
    assert visible_word_count(text) == count


def opt_out_fields():
    return {
        "provider": "neutral-channel",
        "videoId": "next-analysis",
        "selector": "none",
        "previousSelectionRef": {
            "id": "selection-1",
            "documentHash": "b" * 64,
            "path": "decisions/selection-1.json",
        },
        "expectedIndexHash": "c" * 64,
    }


def test_seal_creates_native_identity_and_exact_hash_without_mutating_the_input():
    fields = opt_out_fields()
    original = deepcopy(fields)
    document = seal("BriefOptOutProposal", fields, clock=lambda: "2026-01-04T12:00:00Z")
    assert fields == original
    assert document["createdBy"] == {"type": "native", "id": "avo.direction"}
    assert document["createdAt"] == "2026-01-04T12:00:00Z"
    assert document["documentType"] == "BriefOptOutProposal"
    assert document["documentHash"] == document_hash_excluding(document, "documentHash")
    assert document["id"]
    validate("BriefOptOutProposal", document)


def test_recomputing_hash_rejects_a_same_shape_modified_stored_document():
    document = seal("BriefOptOutProposal", opt_out_fields())
    document["videoId"] = "different-project"
    with pytest.raises(DirectionError) as error:
        validate("BriefOptOutProposal", document)
    assert error.value.code == "DIR_DOCUMENT_CHANGED"


def test_request_validation_uses_typed_dto_without_requiring_stored_hash_fields():
    validate("Context", {"schemaVersion": "1.0.0", "idea": "Compare two approaches."})
    with pytest.raises(DirectionError):
        validate("Context", {"schemaVersion": "1.0.0", "execute": "render"})
    with pytest.raises(DirectionError):
        validate("UnregisteredKind", {})


def test_seal_cannot_import_human_authority_or_a_supplied_hash():
    fields = opt_out_fields()
    fields["createdBy"] = {"type": "human", "id": "creator"}
    fields["documentHash"] = "a" * 64
    with pytest.raises(DirectionError):
        seal("BriefOptOutProposal", fields)


def test_reference_is_exact_and_does_not_mutate_or_add_profile_approval():
    document = seal("BriefOptOutProposal", opt_out_fields())
    value = document_ref(document, "briefs/opt-out.json")
    assert value == {
        "id": document["id"],
        "documentHash": document["documentHash"],
        "path": "briefs/opt-out.json",
    }
    assert "approved" not in value


def test_direction_error_preserves_actionable_metadata():
    error = DirectionError(
        "DIR_INDEX_CONFLICT",
        "Index changed",
        status="conflict",
        details={"current": "a" * 64},
    )
    assert isinstance(error, ValueError)
    assert str(error) == "Index changed"
    assert error.status == "conflict"
    assert error.details["current"] == "a" * 64
