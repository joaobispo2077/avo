"""Content reduction is explicit and candidate-bound, separate from cleanup."""

import pytest

from avo.timeline.cutting_service import CuttingServiceError
from test_cutting_service import CheckedPreview, fixture_service


def setup(tmp_path, **unit_flags):
    preview = CheckedPreview(tmp_path / "candidate.json")
    service, revision = fixture_service(
        tmp_path, preview_port=preview, verification_port=preview
    )
    interval = {
        "sourceId": "dialogue",
        "startTicks": 12000,
        "endTicksExclusive": 24000,
        "timebase": {"num": 1, "den": 48000},
    }
    request = {
        "targetDurationMs": 750,
        "editorialUnits": [
            {
                "unitId": "whole-unit",
                "complete": True,
                "sourceRange": interval,
                "tangent": True,
                "rationale": "Nonessential tangent",
                **unit_flags,
            }
        ],
    }
    result = service.analyze(request)
    proposal = service.status(result["proposalRef"])["proposal"]
    occurrence = next(
        item
        for item in proposal["occurrences"]
        if item.get("editorialApprovalRequired")
    )
    return service, revision, result["proposalRef"], occurrence["occurrenceId"]


def test_duration_target_does_not_authorize_content_removal(tmp_path):
    service, revision, proposal, identity = setup(tmp_path)
    assert service.apply(proposal)["status"] == "needs-review"
    preview = service.preview(proposal)
    with pytest.raises(CuttingServiceError, match="editorialApproval"):
        service.decide(
            proposal,
            {
                "previewRef": preview["verificationRef"],
                "decisions": [
                    {
                        "occurrenceId": identity,
                        "disposition": "remove",
                        "reason": "target duration",
                    }
                ],
            },
        )
    assert service.workspace.store("cmap").head_hash() == revision["contentHash"]


@pytest.mark.parametrize(
    "flags",
    [
        {"central": True},
        {"uniqueQualification": True},
        {"meaningfulExample": True},
        {"protected": True},
        {"complete": False},
    ],
)
def test_central_qualified_and_protected_units_do_not_get_removal_edits(
    tmp_path, flags
):
    service, _, proposal, identity = setup(tmp_path, **flags)
    edits = service.status(proposal)["proposal"]["edits"]
    assert not any(edit["occurrenceId"] == identity for edit in edits)


def test_content_choice_requires_new_exact_candidate_preview(tmp_path):
    service, _, proposal, identity = setup(tmp_path)
    preview = service.preview(proposal)
    decision = {
        "occurrenceId": identity,
        "disposition": "remove",
        "reason": "creator reviewed complete unit",
        "editorialApproval": True,
    }
    service.decide(
        proposal, {"previewRef": preview["verificationRef"], "decisions": [decision]}
    )
    with pytest.raises(CuttingServiceError, match="exact preview"):
        service.apply(proposal)


def test_approved_content_candidate_applies_only_after_fresh_verification(tmp_path):
    service, revision, proposal, identity = setup(tmp_path)
    first = service.preview(proposal)
    decision = {
        "occurrenceId": identity,
        "disposition": "remove",
        "reason": "creator approved complete tangent",
        "editorialApproval": True,
    }
    service.decide(
        proposal, {"previewRef": first["verificationRef"], "decisions": [decision]}
    )
    second = service.preview(proposal)
    assert second["status"] == "pass"
    service.decide(
        proposal, {"previewRef": second["verificationRef"], "decisions": [decision]}
    )
    assert service.apply(proposal)["status"] == "applied"
    assert service.workspace.store("cmap").head_hash() != revision["contentHash"]
