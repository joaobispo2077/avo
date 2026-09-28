from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.approval_service import ApprovalService
from avo.timeline.contracts import file_fingerprint, validate_document
from avo.timeline.delivery import DeliveryError, DeliveryService
from avo.timeline.lifecycle import LifecycleError
from avo.timeline.pipeline import TimelinePipeline


def _bindings(candidate: Path, transcript: Path) -> dict:
    sha256 = file_fingerprint(candidate)["sha256"]
    return {
        "proof_plan": {
            "artifactId": "proof-plan-001",
            "sha256": "a" * 64,
            "iterationId": "iteration-001",
        },
        "materialization": {
            "artifactId": "materialization-001",
            "sha256": "b" * 64,
            "candidateSha256": sha256,
        },
        "transcript": {
            "fingerprint": file_fingerprint(transcript),
            "sourceSha256": sha256,
        },
        "review": {
            "artifactId": "review-001",
            "sha256": "c" * 64,
            "candidateSha256": sha256,
            "proofPlanSha256": "a" * 64,
        },
        "regression_result": {
            "artifactId": "regression-result-001",
            "sha256": "d" * 64,
            "candidateSha256": sha256,
        },
        "approval": {
            "artifactId": "approval-001",
            "sha256": "e" * 64,
            "candidateSha256": sha256,
        },
    }


def _files(workspace) -> tuple[Path, Path]:
    candidate = workspace.raw_dir / "edit" / "proofs" / "candidate.mp4"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate-one")
    transcript = workspace.raw_dir / "edit" / "transcripts" / "candidate.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps({"source": {"sha256": file_fingerprint(candidate)["sha256"]}}),
        encoding="utf-8",
    )
    return candidate, transcript


def test_stage_specific_snapshots_are_immutable_and_schema_valid(
    footage_project_factory,
):
    workspace = footage_project_factory(video_id="candidate-states")
    candidate, transcript = _files(workspace)
    bindings = _bindings(candidate, transcript)
    pipeline = TimelinePipeline(workspace)

    rendered = pipeline.record_candidate_snapshot(
        state="rendered",
        candidate=candidate,
        iteration_id="iteration-001",
        proof_plan=bindings["proof_plan"],
        materialization=bindings["materialization"],
        expected_active_snapshot_hash=None,
    )
    reviewing = pipeline.record_candidate_snapshot(
        state="reviewing",
        candidate=candidate,
        iteration_id="iteration-001",
        proof_plan=bindings["proof_plan"],
        materialization=bindings["materialization"],
        transcript=bindings["transcript"],
        expected_active_snapshot_hash=rendered["snapshotHash"],
    )
    needs_human = pipeline.record_candidate_snapshot(
        state="needs-human",
        candidate=candidate,
        iteration_id="iteration-001",
        proof_plan=bindings["proof_plan"],
        materialization=bindings["materialization"],
        transcript=bindings["transcript"],
        review=bindings["review"],
        regression_result=bindings["regression_result"],
        expected_active_snapshot_hash=reviewing["snapshotHash"],
    )
    approved = pipeline.record_candidate_snapshot(
        state="approved",
        candidate=candidate,
        iteration_id="iteration-001",
        proof_plan=bindings["proof_plan"],
        materialization=bindings["materialization"],
        transcript=bindings["transcript"],
        review=bindings["review"],
        regression_result=bindings["regression_result"],
        approval=bindings["approval"],
        expected_active_snapshot_hash=needs_human["snapshotHash"],
    )

    for snapshot in (rendered, reviewing, needs_human, approved):
        validate_document(snapshot, "avo.candidate-snapshot.schema.json")
        path = pipeline.candidate_snapshot_path(snapshot)
        assert json.loads(path.read_text(encoding="utf-8")) == snapshot
    assert rendered["transcript"] is None
    assert reviewing["review"] is None
    assert needs_human["approval"] is None
    assert approved["supersedesSnapshotId"] == needs_human["snapshotId"]

    wrong_bytes = {"sha256": "f" * 64, "sizeBytes": 1}
    with pytest.raises(ValueError, match="bytes differ"):
        ApprovalService(workspace)._require_candidate_snapshot(
            wrong_bytes["sha256"], wrong_bytes["sizeBytes"]
        )
    with pytest.raises(DeliveryError, match="bytes differ"):
        DeliveryService(workspace)._require_candidate_snapshot(wrong_bytes)
    assert DeliveryService(workspace)._require_candidate_snapshot(
        approved["candidate"]
    ) == {"snapshotId": approved["snapshotId"], "sha256": approved["snapshotHash"]}


@pytest.mark.parametrize(
    ("state", "omitted", "message"),
    [
        ("reviewing", "transcript", "transcript"),
        ("needs-human", "regression_result", "regression"),
        ("approved", "approval", "approval"),
    ],
)
def test_stage_requirements_fail_closed(
    footage_project_factory, state, omitted, message
):
    workspace = footage_project_factory(video_id=f"missing-{state}")
    candidate, transcript = _files(workspace)
    bindings = _bindings(candidate, transcript)
    pipeline = TimelinePipeline(workspace)
    rendered = pipeline.record_candidate_snapshot(
        state="rendered",
        candidate=candidate,
        iteration_id="iteration-001",
        proof_plan=bindings["proof_plan"],
        materialization=bindings["materialization"],
        expected_active_snapshot_hash=None,
    )
    kwargs = {
        "transcript": bindings["transcript"],
        "review": bindings["review"],
        "regression_result": bindings["regression_result"],
        "approval": bindings["approval"],
    }
    kwargs[omitted] = None
    with pytest.raises(ValueError, match=message):
        pipeline.record_candidate_snapshot(
            state=state,
            candidate=candidate,
            iteration_id="iteration-001",
            proof_plan=bindings["proof_plan"],
            materialization=bindings["materialization"],
            expected_active_snapshot_hash=rendered["snapshotHash"],
            **kwargs,
        )


def test_stale_cas_and_mixed_candidate_binding_leave_active_snapshot_unchanged(
    footage_project_factory,
):
    workspace = footage_project_factory(video_id="candidate-cas")
    candidate, transcript = _files(workspace)
    bindings = _bindings(candidate, transcript)
    pipeline = TimelinePipeline(workspace)
    rendered = pipeline.record_candidate_snapshot(
        state="rendered",
        candidate=candidate,
        iteration_id="iteration-001",
        proof_plan=bindings["proof_plan"],
        materialization=bindings["materialization"],
        expected_active_snapshot_hash=None,
    )
    with pytest.raises(LifecycleError, match="compare-and-swap"):
        pipeline.record_candidate_snapshot(
            state="reviewing",
            candidate=candidate,
            iteration_id="iteration-001",
            proof_plan=bindings["proof_plan"],
            materialization=bindings["materialization"],
            transcript=bindings["transcript"],
            expected_active_snapshot_hash="f" * 64,
        )
    reviewing = pipeline.record_candidate_snapshot(
        state="reviewing",
        candidate=candidate,
        iteration_id="iteration-001",
        proof_plan=bindings["proof_plan"],
        materialization=bindings["materialization"],
        transcript=bindings["transcript"],
        expected_active_snapshot_hash=rendered["snapshotHash"],
    )
    wrong = dict(bindings["review"])
    wrong["candidateSha256"] = "f" * 64
    with pytest.raises(ValueError, match="candidate"):
        pipeline.record_candidate_snapshot(
            state="needs-human",
            candidate=candidate,
            iteration_id="iteration-001",
            proof_plan=bindings["proof_plan"],
            materialization=bindings["materialization"],
            transcript=bindings["transcript"],
            review=wrong,
            regression_result=bindings["regression_result"],
            expected_active_snapshot_hash=reviewing["snapshotHash"],
        )
    stale_review = dict(bindings["review"])
    stale_review["proofPlanSha256"] = "f" * 64
    with pytest.raises(ValueError, match="proof plan"):
        pipeline.record_candidate_snapshot(
            state="needs-human",
            candidate=candidate,
            iteration_id="iteration-001",
            proof_plan=bindings["proof_plan"],
            materialization=bindings["materialization"],
            transcript=bindings["transcript"],
            review=stale_review,
            regression_result=bindings["regression_result"],
            expected_active_snapshot_hash=reviewing["snapshotHash"],
        )
    wrong_fingerprint = {**file_fingerprint(candidate), "sha256": "f" * 64}
    with pytest.raises(ValueError, match="fingerprint bytes differ"):
        pipeline.record_candidate_snapshot(
            state="rendered",
            candidate=wrong_fingerprint,
            iteration_id="iteration-001",
            proof_plan=bindings["proof_plan"],
            materialization=bindings["materialization"],
            expected_active_snapshot_hash=reviewing["snapshotHash"],
        )
    active = pipeline.active_candidate_snapshot()
    assert active["snapshotHash"] == reviewing["snapshotHash"]
