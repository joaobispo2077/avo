from __future__ import annotations

from types import SimpleNamespace

from avo.timeline.command_handlers import CommandHandlers
from avo.timeline.iterations import IterationLedgerService

SHA = "a" * 64


def _workspace(tmp_path):
    timeline = tmp_path / "edit" / "timeline"
    timeline.mkdir(parents=True)
    return SimpleNamespace(
        timeline_dir=timeline,
        video_id="video-1",
        project={"provider": "bishop"},
    )


def _iteration(item):
    return {
        "intent": {"requestedChanges": ["repair sync"]},
        "canonicalBasis": {"cmap": SHA},
        "proofPlanRef": {"artifactId": "proof-plan-0001", "sha256": SHA},
        "reworkItems": [item],
    }


def _classification(origin, *, supersedes=None, confidence=0.9):
    return {
        "origin": origin,
        "summary": "Correct the insert and SFX synchronization.",
        "impact": {
            "affectedArtifacts": ["tracks", "animation"],
            "programWindows": [
                {
                    "windowId": "insert-sync",
                    "startFrame": 300,
                    "endFrameExclusive": 390,
                    "reason": "entry transient is displaced",
                }
            ],
            "renderCost": 2,
            "reviewCost": 1,
        },
        "evidenceRefs": [{"evidenceId": "review-0001", "sha256": SHA}],
        "confidence": confidence,
        "capabilityGap": None,
        "supersedes": supersedes,
    }


class Pipeline:
    def __init__(self, workspace):
        self.workspace = workspace

    def candidate_status(self):
        return {"snapshotId": "candidate-0001", "state": "rendered"}

    def proof_build_status(self, **_payload):
        return {"status": "ready-for-microproof"}


def test_proof_status_exposes_active_rework_evidence_impact_and_confidence(tmp_path):
    workspace = _workspace(tmp_path)
    service = IterationLedgerService(workspace)
    first = service.record_iteration(
        _iteration(_classification("implementation-defect")),
        actor="agent",
        reason="initial evidence",
    )
    original = first["ledger"]["reworkItems"][0]
    service.record_iteration(
        _iteration(
            _classification(
                "unknown",
                supersedes=original["reworkId"],
                confidence=0.0,
            )
        ),
        actor="agent",
        reason="classification corrected after review",
    )

    status = CommandHandlers(Pipeline(workspace)).execute("pipeline", "proof-status")

    rework = status["rework"]
    assert rework["classificationCount"] == 1
    assert rework["items"][0]["origin"] == "unknown"
    assert rework["items"][0]["evidenceRefs"][0]["evidenceId"] == "review-0001"
    assert rework["items"][0]["impact"]["renderCost"] == 2
    assert rework["items"][0]["confidence"] == 0.0
    assert [item["status"] for item in rework["classificationHistory"]] == [
        "superseded",
        "active",
    ]
    assert (
        rework["classificationHistory"][0]["supersededBy"]
        == rework["classificationHistory"][1]["reworkId"]
    )
    assert rework["classificationHistory"][1]["supersedes"] == original["reworkId"]


def test_detailed_proof_status_includes_the_same_rework_history(tmp_path):
    workspace = _workspace(tmp_path)
    IterationLedgerService(workspace).record_iteration(
        _iteration(_classification("implementation-defect")),
        actor="agent",
        reason="classify regression",
    )

    status = CommandHandlers(Pipeline(workspace)).execute(
        "pipeline",
        "proof-status",
        {"proofPlan": {"proofPlanId": "proof-plan-0001"}},
    )

    assert status["result"]["rework"]["classificationCount"] == 1
    assert status["result"]["rework"]["classificationHistory"][0]["status"] == "active"
