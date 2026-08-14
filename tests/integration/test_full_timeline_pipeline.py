from __future__ import annotations

from pathlib import Path
import subprocess

from avo.timeline.animation import AnimationService
from avo.timeline.bmap_service import BMapService
from avo.timeline.contracts import dependency_lock_hash, file_fingerprint
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.review import CHECKPOINT_POLICIES, candidate_identity
from avo.timeline.tracks import TracksService
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_bmap_service import approved_workspace, cue
from tests.test_timeline_tracks_service import canonical_tracks


def encoded_candidate(path: Path) -> Path:
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=24:d=1",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-shortest", "-c:v", "libx264", "-c:a", "aac", str(path),
    ], check=True)
    return path


def review_package(checkpoint: str, candidate: Path, dependencies: dict[str, str]):
    identity = candidate_identity(candidate, dependencies, checkpoint)
    evidence = []
    for kind in CHECKPOINT_POLICIES[checkpoint]["required"]:
        evidence.append({
            "kind": kind,
            "status": "pass",
            "candidateHash": identity["sha256"],
            "candidateIdentityHash": identity["identityHash"],
            "dependencyLockSha256": dependency_lock_hash(dependencies),
            "dependencyHashes": dependencies,
            "scope": {"mode": "full"},
            "coverage": {"requiredWindows": 0, "reviewedWindows": 0},
        })
    review = {
        "state": "ai-passed",
        "checkpoint": checkpoint,
        "candidate": identity,
        "dependencyLockSha256": dependency_lock_hash(dependencies),
        "evidence": evidence,
    }
    approval = {
        "checkpoint": checkpoint,
        "decision": "approved",
        "candidateIdentityHash": identity["identityHash"],
        "candidateSha256": identity["sha256"],
        "dependencyLockSha256": review["dependencyLockSha256"],
    }
    return review, approval


def test_complete_persisted_ai_first_lifecycle(tmp_path: Path):
    workspace, _, cut_hash = approved_workspace(tmp_path)
    pipeline = TimelinePipeline(workspace)
    candidate = encoded_candidate(tmp_path / "candidate.mp4")
    pipeline.advance(
        "sources-ready",
        rawInventory={"sources": [{"sourceId": "raw", "sha256": file_fingerprint(workspace.raw_dir / "raw.bin")["sha256"]}]},
    )
    pipeline.advance("sync-ready")
    pipeline.advance("cmap-draft")
    pipeline.advance("cut-ai-review", candidate=candidate)
    cut_deps = workspace.active_dependency_snapshot()
    cut_review, cut_approval = review_package("cut-proof", candidate, cut_deps)
    pipeline.advance("cmap-approved", review=cut_review, approval=cut_approval)

    BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="B-time")
    TracksService(workspace).author(
        canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
        actor="avo", reason="assembly",
    )
    AnimationService(workspace).author(strategy(), actor="avo", reason="motion")
    assert pipeline.status()["pipeline"]["mainState"] == "bmap-draft"
    pipeline.advance("assembly-ai-review", candidate=candidate)
    motion_deps = workspace.active_dependency_snapshot()
    motion_review, motion_approval = review_package("motion-proof", candidate, motion_deps)
    pipeline.advance("picture-locked", review=motion_review, approval=motion_approval)
    pipeline.advance("finishing")
    pipeline.advance("pre-master-ai-review", candidate=candidate)
    pre_review, pre_approval = review_package("pre-master", candidate, motion_deps)
    pipeline.advance("master-approved", review=pre_review, approval=pre_approval)

    master_hash = file_fingerprint(candidate)["sha256"]
    delivered = pipeline.advance(
        "delivered",
        deliveryManifest={
            "state": "delivered",
            "master": {"sha256": master_hash},
            "transcript": {"sourceSha256": master_hash},
        },
    )
    assert delivered["mainState"] == "delivered"
    assert delivered["sideState"] is None
    assert len(delivered["transitionHistory"]) == 12
