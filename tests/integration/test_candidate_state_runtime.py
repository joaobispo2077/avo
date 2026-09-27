from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.command_handlers import CommandHandlers
from avo.timeline.contracts import file_fingerprint
from avo.timeline.lifecycle import LifecycleError
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.reconstruction import build_reconstruction_bundle
from avo.timeline.store import atomic_write_json


def _binding_set(candidate: Path, transcript: Path) -> dict:
    candidate_sha = file_fingerprint(candidate)["sha256"]
    return {
        "proof_plan": {
            "artifactId": "proof-plan-runtime",
            "sha256": "1" * 64,
            "iterationId": "iteration-runtime",
        },
        "materialization": {
            "artifactId": "materialization-runtime",
            "sha256": "2" * 64,
            "candidateSha256": candidate_sha,
        },
        "transcript": {
            "fingerprint": file_fingerprint(transcript),
            "sourceSha256": candidate_sha,
        },
        "review": {
            "artifactId": "review-runtime",
            "sha256": "3" * 64,
            "candidateSha256": candidate_sha,
            "proofPlanSha256": "1" * 64,
        },
        "regression_result": {
            "artifactId": "regression-runtime",
            "sha256": "4" * 64,
            "candidateSha256": candidate_sha,
        },
        "approval": {
            "artifactId": "approval-runtime",
            "sha256": "5" * 64,
            "candidateSha256": candidate_sha,
        },
    }


def test_atomic_candidate_state_status_and_reconstruction_preservation(
    footage_project_factory,
):
    workspace = footage_project_factory(video_id="candidate-runtime")
    candidate = workspace.raw_dir / "edit" / "proofs" / "candidate.mp4"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"reviewed-candidate")
    candidate_sha = file_fingerprint(candidate)["sha256"]
    transcript = workspace.raw_dir / "edit" / "transcripts" / "candidate.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps({"source": {"sha256": candidate_sha}}), encoding="utf-8"
    )
    bindings = _binding_set(candidate, transcript)
    pipeline = TimelinePipeline(workspace)

    run = pipeline.run_store.load()
    run["activeRefs"].update(
        {
            "candidatePath": "stale.mp4",
            "cutCandidateSha256": "f" * 64,
            "reviewIdentityHash": "e" * 64,
            "iterationLedger": {
                "revisionId": "iteration-ledger-r0001",
                "sha256": "d" * 64,
            },
        }
    )
    atomic_write_json(workspace.pipeline_run_path, run)
    rendered = pipeline.record_candidate_snapshot(
        state="rendered",
        candidate=candidate,
        iteration_id="iteration-runtime",
        proof_plan=bindings["proof_plan"],
        materialization=bindings["materialization"],
        expected_active_snapshot_hash=None,
    )
    active_refs = pipeline.run_store.load()["activeRefs"]
    assert set(active_refs) == {"activeCandidateSnapshot", "iterationLedger"}
    assert active_refs["activeCandidateSnapshot"]["sha256"] == rendered["snapshotHash"]

    reviewing = pipeline.record_candidate_snapshot(
        state="reviewing",
        candidate=candidate,
        iteration_id="iteration-runtime",
        proof_plan=bindings["proof_plan"],
        materialization=bindings["materialization"],
        transcript=bindings["transcript"],
        expected_active_snapshot_hash=rendered["snapshotHash"],
    )
    rejected = pipeline.record_candidate_snapshot(
        state="rejected",
        candidate=candidate,
        iteration_id="iteration-runtime",
        proof_plan=bindings["proof_plan"],
        materialization=bindings["materialization"],
        transcript=bindings["transcript"],
        review=bindings["review"],
        regression_result=bindings["regression_result"],
        expected_active_snapshot_hash=reviewing["snapshotHash"],
    )
    status = CommandHandlers(pipeline).execute("pipeline", "proof-status")
    assert status["candidate"]["snapshotHash"] == rejected["snapshotHash"]
    assert status["candidate"]["state"] == "rejected"

    with pytest.raises(LifecycleError, match="compare-and-swap"):
        pipeline.record_candidate_snapshot(
            state="rendered",
            candidate=candidate,
            iteration_id="iteration-runtime",
            proof_plan=bindings["proof_plan"],
            materialization=bindings["materialization"],
            expected_active_snapshot_hash=rendered["snapshotHash"],
        )
    assert (
        pipeline.active_candidate_snapshot()["snapshotHash"] == rejected["snapshotHash"]
    )

    raw = workspace.raw_dir / "raw" / "source.mp4"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"raw-source")
    basename = "20260927-candidate-runtime-master-v001"
    master = workspace.raw_dir / "edit" / "masters" / f"{basename}.mp4"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"master")
    final_transcript = workspace.raw_dir / "edit" / "transcripts" / f"{basename}.json"
    final_transcript.write_text(
        json.dumps({"source": {"sha256": file_fingerprint(master)["sha256"]}}),
        encoding="utf-8",
    )
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    snapshot_paths = {item["path"] for item in bundle["candidateSnapshots"]}
    expected = {
        path.relative_to(workspace.raw_dir).as_posix()
        for path in (workspace.timeline_dir / "candidate-snapshots").rglob("*.json")
    }
    assert snapshot_paths == expected
    pipeline_entry = next(
        item for item in bundle["files"] if item["path"].endswith("pipeline-run.json")
    )
    preserved_run = json.loads(
        (workspace.raw_dir / pipeline_entry["path"]).read_text(encoding="utf-8")
    )
    assert [
        key for key in preserved_run["activeRefs"] if "candidate" in key.lower()
    ] == ["activeCandidateSnapshot"]
