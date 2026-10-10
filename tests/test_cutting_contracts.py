from copy import deepcopy

import pytest

from avo.timeline.contracts import ContractError
from avo.timeline.cutting_contracts import (
    make_document,
    occurrence_id,
    validate_cutting_document,
    validate_source_range,
)


def test_document_hash_binds_payload_and_strict_fields():
    document = make_document("policy", {"enabled": False})
    assert validate_cutting_document(document) == document
    corrupted = deepcopy(document)
    corrupted["payload"]["enabled"] = True
    with pytest.raises(ContractError):
        validate_cutting_document(corrupted)
    with pytest.raises(ContractError):
        make_document("policy", {"enabled": False, "surprise": 1})


@pytest.mark.parametrize(
    "start,end", [(True, 2), (1, 1), (2, 1), (-1, 1), (0.1, 2), (1.0, 2)]
)
def test_source_ranges_reject_invalid_half_open_clocks(start, end):
    with pytest.raises(ContractError):
        validate_source_range(
            {
                "sourceId": "raw",
                "startTicks": start,
                "endTicksExclusive": end,
                "timebase": {"num": 1, "den": 48000},
            }
        )


def test_occurrence_identity_uses_source_anchor():
    first = occurrence_id("a" * 64, "raw", {"startTicks": 10, "unitId": "sentence-1"})
    assert first == occurrence_id(
        "a" * 64, "raw", {"unitId": "sentence-1", "startTicks": 10}
    )
    assert first != occurrence_id(
        "b" * 64, "raw", {"startTicks": 10, "unitId": "sentence-1"}
    )


def test_measurement_can_be_unknown_but_analysis_failure_is_not_silence():
    document = make_document(
        "source-analysis",
        {
            "sourceRef": {"locator": "raw", "sha256": "a" * 64},
            "status": "blocked",
            "language": "pt",
            "measurements": {"runtimeSeconds": None},
            "alignment": {"status": "unsupported", "characters": []},
        },
    )
    assert (
        validate_cutting_document(document)["payload"]["measurements"]["runtimeSeconds"]
        is None
    )


def test_proposal_requires_canonical_basis_and_reservation_budget():
    with pytest.raises(ContractError):
        make_document("proposal", {"occurrences": []})
    with pytest.raises(ContractError):
        make_document(
            "repair-reservation",
            {
                "occurrenceId": "occ-1",
                "ordinal": 3,
                "actor": "avo",
                "proposalRef": {"locator": "p", "sha256": "a" * 64},
                "selectionHash": "b" * 64,
                "reservedAt": "2026-10-10T00:00:00Z",
                "status": "reserved",
            },
        )


def test_protected_interval_is_checked_inside_a_policy():
    with pytest.raises(ContractError):
        make_document(
            "policy",
            {
                "enabled": True,
                "protectedEvents": [
                    {
                        "eventId": "quiz",
                        "role": "quiz",
                        "reason": "answer hold",
                        "sourceRange": {
                            "sourceId": "raw",
                            "startTicks": 100,
                            "endTicksExclusive": 100,
                            "timebase": {"num": 1, "den": 48000},
                        },
                    }
                ],
            },
        )


def test_verification_and_decision_are_distinct_from_canonical_selection():
    reference = {"locator": "artifact.json", "sha256": "a" * 64}
    verification = make_document(
        "verification",
        {"proposalRef": reference, "candidateRef": reference, "status": "needs-human"},
    )
    assert validate_cutting_document(verification, "verification") == verification
    with pytest.raises(ContractError):
        validate_cutting_document(verification, "decision")
    decision = make_document(
        "decision",
        {
            "actor": "human",
            "decidedAt": "2026-10-10T00:00:00Z",
            "occurrenceId": "occ-1",
            "disposition": "keep",
            "proposalRef": reference,
            "previewRef": reference,
            "reason": "preserve uncertainty",
        },
    )
    assert decision["documentType"] == "decision"
