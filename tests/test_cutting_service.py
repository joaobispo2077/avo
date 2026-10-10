"""Proposal evidence must not silently become canonical selections."""

import pytest

from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.cutting_audit import audit_joins
from avo.timeline.cutting_policy import resolve_cutting_policy
from avo.timeline.cutting_service import (
    CuttingService,
    CuttingServiceError,
    _validate_decision,
)
from cutting_fixtures import cutting_workspace, source_snapshot


def fixture_service(tmp_path, **ports):
    workspace, source = cutting_workspace(tmp_path)
    revision = CMapService(workspace).author(
        source_snapshot(source), actor="fixture", reason="canonical original"
    )
    policy = resolve_cutting_policy(
        project_settings={"enabled": True, "family": "analysis-review"}
    )
    return CuttingService(workspace, policy=policy, **ports), revision


def test_human_alternative_cannot_silently_change_a_previewed_retake():
    occurrence = {
        "occurrenceId": "retake",
        "disposition": "replace",
        "selectedAlternativeId": "earlier",
    }
    proposal = {"edits": [{"occurrenceId": "retake"}]}
    with pytest.raises(CuttingServiceError, match="alternative"):
        _validate_decision(
            {"disposition": "replace", "alternativeId": "later"},
            occurrence,
            {"status": "pass"},
            proposal,
        )


def test_missing_analysis_is_visible_and_does_not_mutate_cmap(tmp_path):
    service, revision = fixture_service(tmp_path)
    result = service.analyze()
    assert result["status"] == "needs-review"
    assert service.workspace.store("cmap").head_hash() == revision["contentHash"]
    assert result["coverage"]["unobservedSources"] == ["dialogue"]


def test_requested_rational_frame_rate_is_bound_to_the_proposal(tmp_path):
    service, _ = fixture_service(tmp_path)
    rate = {"num": 30000, "den": 1001}
    ref = service.analyze({"frameRate": rate})["proposalRef"]
    assert service.status(ref)["proposal"]["frameRate"] == rate


def test_disabled_analysis_does_not_create_proposal_or_selection(tmp_path):
    service, revision = fixture_service(tmp_path)
    service.policy = resolve_cutting_policy()
    result = service.analyze()
    assert result["status"] == "disabled"
    assert "proposalRef" not in result
    assert service.workspace.store("cmap").head_hash() == revision["contentHash"]


def test_stale_proposal_blocks_preview_and_apply(tmp_path):
    service, _ = fixture_service(tmp_path)
    proposal = service.analyze()["proposalRef"]
    current = service.workspace.store("cmap").load()["revisions"][-1]["snapshot"]
    current["segments"][0]["reason"] = "changed canonical intent"
    CMapService(service.workspace).author(current, actor="fixture", reason="change")
    for method in (service.preview, service.apply):
        with pytest.raises(CuttingServiceError, match="stale"):
            method(proposal)


def test_unverified_preview_cannot_be_approved_as_repaired(tmp_path):
    service, _ = fixture_service(tmp_path)
    proposal = service.analyze()["proposalRef"]
    assert service.preview(proposal)["status"] == "blocked"
    with pytest.raises(CuttingServiceError, match="preview"):
        service.decide(
            proposal,
            {"decisions": [{"occurrenceId": "unknown", "disposition": "shorten"}]},
        )


def test_ref_cannot_escape_cutting_directory(tmp_path):
    service, _ = fixture_service(tmp_path)
    with pytest.raises(CuttingServiceError, match="directory"):
        service.status(tmp_path / "untrusted.json")


class ObservedAnalysis:
    def analyze(self, source, **request):
        interval = {
            **request["source_range"],
            "startTicks": 4800,
            "endTicksExclusive": 43200,
        }
        return {
            "sourceRef": {
                "locator": str(source),
                "sha256": request["fingerprint"]["sha256"],
            },
            "syncRef": request["sync_ref"],
            "routing": request["selection"],
            "preprocessing": {"sourceRange": request["source_range"]},
            "status": "pass",
            "coverage": {"observed": True},
            "pauseCandidates": [
                {
                    "sourceRange": interval,
                    "evidence": {
                        "quietRanges": [interval],
                        "speechRanges": [],
                        "acousticObserved": True,
                        "wordEdges": {
                            "status": "observed",
                            "beforeEndTicks": 4700,
                            "afterStartTicks": 43300,
                        },
                        "context": {"dispensable": True, "intentionalPause": False},
                        "adjacentWords": {"before": "completa", "after": "Seguinte"},
                    },
                }
            ],
        }


class CheckedPreview:
    def __init__(self, path):
        self.path = path
        self.calls = 0

    def render(self, snapshot, **request):
        self.calls += 1
        self.path.write_text("generated test candidate", encoding="utf-8")
        return {
            "candidate": self.path,
            "verificationRequest": {
                "graph_hash": content_hash(snapshot),
                "required_occurrences": sorted(
                    {edit["occurrenceId"] for edit in request["proposal"]["edits"]}
                    | {
                        join["joinId"]
                        for join in audit_joins(snapshot, {"num": 30, "den": 1})
                    }
                ),
            },
        }

    def verify(self, candidate, *, proposal_ref, graph_hash, required_occurrences):
        return {
            "proposalRef": proposal_ref,
            "candidateRef": {
                "locator": str(candidate),
                "sha256": file_fingerprint(candidate)["sha256"],
            },
            "graphHash": graph_hash,
            "occurrenceCoverage": required_occurrences,
            "checks": [{"kind": "injected-test-verifier", "status": "pass"}],
            "status": "pass",
        }


def test_apply_requires_verified_exact_candidate_and_invalidates_dependents(tmp_path):
    preview = CheckedPreview(tmp_path / "candidate.json")
    service, revision = fixture_service(
        tmp_path,
        analysis_port=ObservedAnalysis(),
        preview_port=preview,
        verification_port=preview,
    )
    proposal_ref = service.analyze()["proposalRef"]
    proposal = service.status(proposal_ref)["proposal"]
    assert len(proposal["edits"]) == 1
    assert service.apply(proposal_ref)["status"] == "needs-review"
    result = service.preview(proposal_ref)
    service.decide(
        proposal_ref,
        {
            "previewRef": result["verificationRef"],
            "decisions": [
                {
                    "occurrenceId": proposal["occurrences"][0]["occurrenceId"],
                    "disposition": "shorten",
                    "reason": "listened test",
                }
            ],
        },
    )
    applied = service.apply(proposal_ref)
    assert applied["status"] == "applied"
    assert applied["revision"]["contentHash"] != revision["contentHash"]
    selected = applied["revision"]["snapshot"]["segments"]
    assert len(selected) == 2
    assert selected[0]["out"]["ticks"] < selected[1]["in"]["ticks"]


def test_changed_encoded_candidate_blocks_apply(tmp_path):
    preview = CheckedPreview(tmp_path / "candidate.json")
    service, _ = fixture_service(
        tmp_path,
        analysis_port=ObservedAnalysis(),
        preview_port=preview,
        verification_port=preview,
    )
    proposal = service.analyze()["proposalRef"]
    identity = service.status(proposal)["proposal"]["occurrences"][0]["occurrenceId"]
    verified = service.preview(proposal)
    service.decide(
        proposal,
        {
            "previewRef": verified["verificationRef"],
            "decisions": [
                {"occurrenceId": identity, "disposition": "shorten", "reason": "test"}
            ],
        },
    )
    preview.path.write_text("changed bytes", encoding="utf-8")
    with pytest.raises(CuttingServiceError, match="candidate"):
        service.apply(proposal)


def test_resume_reuses_only_unchanged_verified_preview(tmp_path):
    preview = CheckedPreview(tmp_path / "candidate.json")
    service, _ = fixture_service(
        tmp_path,
        analysis_port=ObservedAnalysis(),
        preview_port=preview,
        verification_port=preview,
    )
    proposal = service.analyze()["proposalRef"]
    first = service.preview(proposal)
    resumed = CuttingService(
        service.workspace,
        policy=service.policy,
        preview_port=preview,
        verification_port=preview,
    )
    second = resumed.preview(proposal)
    assert preview.calls == 1
    assert second["verificationRef"] == first["verificationRef"]
    assert second["cached"] is True


def test_canonical_hold_cannot_be_weakened_by_profile(tmp_path):
    service, _ = fixture_service(tmp_path, analysis_port=ObservedAnalysis())
    snapshot = service._current()["snapshot"]
    snapshot["protectedQuizWindows"] = [
        {
            "sourceBasename": "original.wav",
            "start": 0.1,
            "end": 0.9,
            "minimumAnswerSeconds": 0.8,
        }
    ]
    CMapService(service.workspace).author(
        snapshot, actor="fixture", reason="protect answer"
    )
    proposal_ref = service.analyze()["proposalRef"]
    assert service.status(proposal_ref)["proposal"]["edits"] == []


def test_review_decision_can_rebind_same_choice_to_new_exact_preview(tmp_path):
    preview = CheckedPreview(tmp_path / "candidate.json")
    service, _ = fixture_service(
        tmp_path,
        analysis_port=ObservedAnalysis(),
        preview_port=preview,
        verification_port=preview,
    )
    proposal = service.analyze()["proposalRef"]
    identity = service.status(proposal)["proposal"]["occurrences"][0]["occurrenceId"]
    result = service.preview(proposal)
    request = {
        "previewRef": result["verificationRef"],
        "decisions": [
            {"occurrenceId": identity, "disposition": "shorten", "reason": "checked"}
        ],
    }
    first = service.decide(proposal, request)
    service.decide(
        proposal,
        {
            **request,
            "decisions": [{**request["decisions"][0], "reason": "checked again"}],
        },
    )
    latest = service.status(proposal)["decisions"][identity]
    assert latest["supersedesRef"] == first["decisionRefs"][0]
    assert service.apply(proposal)["status"] == "applied"


def test_passing_verifier_must_cover_every_selected_occurrence_and_join(tmp_path):
    class IncompletePreview(CheckedPreview):
        def verify(self, *args, **kwargs):
            result = super().verify(*args, **kwargs)
            result["occurrenceCoverage"] = []
            return result

    preview = IncompletePreview(tmp_path / "candidate.json")
    service, original = fixture_service(
        tmp_path,
        analysis_port=ObservedAnalysis(),
        preview_port=preview,
        verification_port=preview,
    )
    proposal = service.analyze()["proposalRef"]
    with pytest.raises(CuttingServiceError, match="coverage"):
        service.preview(proposal)
    assert service.workspace.store("cmap").head_hash() == original["contentHash"]


def test_blocked_analysis_cannot_propose_removal_from_partial_candidates(tmp_path):
    class PartialAnalysis(ObservedAnalysis):
        def analyze(self, *args, **kwargs):
            result = super().analyze(*args, **kwargs)
            result["status"] = "blocked"
            return result

    service, _ = fixture_service(tmp_path, analysis_port=PartialAnalysis())
    proposal = service.status(service.analyze()["proposalRef"])["proposal"]
    assert not proposal["edits"]
    assert proposal["occurrences"][0]["disposition"] == "needs-review"


def test_apply_rechecks_hard_protection_even_for_forged_proposal(tmp_path):
    preview = CheckedPreview(tmp_path / "candidate.json")
    service, original = fixture_service(
        tmp_path,
        analysis_port=ObservedAnalysis(),
        preview_port=preview,
        verification_port=preview,
    )
    ref = service.analyze()["proposalRef"]
    payload = service.status(ref)["proposal"]
    identity = payload["occurrences"][0]["occurrenceId"]
    verified = service.preview(ref)
    service.decide(
        ref,
        {
            "previewRef": verified["verificationRef"],
            "decisions": [
                {
                    "occurrenceId": identity,
                    "disposition": "shorten",
                    "reason": "checked",
                }
            ],
        },
    )
    # A persisted proposal is still untrusted at the application boundary.
    protection = {
        "eventId": "locked",
        "sourceRange": payload["occurrences"][0]["sourceRange"],
    }
    from dataclasses import replace

    service.policy = replace(service.policy, protections=(protection,))
    with pytest.raises(CuttingServiceError, match="protected"):
        service.apply(ref)
    assert service.workspace.store("cmap").head_hash() == original["contentHash"]
