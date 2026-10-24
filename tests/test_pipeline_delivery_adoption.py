"""Administrative adoption preserves history and requires the union of real gates."""

from __future__ import annotations

import copy

import pytest

from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.delivery import DeliveryService
from avo.timeline.lifecycle import LifecycleError, TransitionFacts
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.review import CHECKPOINT_POLICIES, GateError
from avo.timeline.store import atomic_write_json
from test_delivery_adoption import adoption as adoption_fixture


@pytest.fixture
def delivery_adoption(tmp_path, monkeypatch):
    original_init = TimelinePipeline.__init__

    def build(*, omit=None, source=True, external=False):
        data = adoption_fixture.__wrapped__(tmp_path, monkeypatch)
        monkeypatch.setattr(TimelinePipeline, "__init__", original_init)
        workspace = data.service.workspace
        workspace.timeline_dir = tmp_path / "edit" / "timeline"
        workspace.require_active = lambda name: {
            "headRevisionId": f"{name}-r0001",
            "activeState": "valid",
        }
        workspace.pipeline_run_path.unlink()
        pipeline = TimelinePipeline(workspace)
        pipeline.run_store.initialize(
            run_id="adoption-test",
            video_id="adoption-test",
            provider="fixture",
            project_path=tmp_path / "avo.project.json",
        )
        current = pipeline.run_store.advance(
            "sources-ready", TransitionFacts(), actor="fixture", reason="prior event"
        )
        current["mainState"] = "bmap-draft"
        current["activeRefs"]["activeCandidateSnapshot"] = {
            "snapshotId": data.snapshot["snapshotId"],
            "sha256": data.snapshot["snapshotHash"],
        }
        atomic_write_json(workspace.pipeline_run_path, current)
        required = set().union(
            *(
                CHECKPOINT_POLICIES[name]["required"]
                for name in ("motion-proof", "pre-master", "deliver")
            )
        )
        existing = {item["kind"] for item in data.review["evidence"]}
        for kind in sorted(required - existing):
            item = copy.deepcopy(data.review["evidence"][0])
            item.update(kind=kind, evidenceId=kind)
            data.review["evidence"].append(item)
        data.review["evidence"] = [
            item for item in data.review["evidence"] if item["kind"] != omit
        ]
        atomic_write_json(data.review_path, data.review)
        source_path = workspace.timeline_dir / "prior-creator-approval.json"
        prior = {
            "candidateSha256": data.review["candidate"]["sha256"],
            "decision": "approved",
            "actor": {"type": "user", "id": "creator"},
            "occurredAt": "2026-10-14T12:00:00Z",
            "scope": "exact-master",
        }
        atomic_write_json(source_path, prior)
        source_ref = {
            "path": str(source_path.resolve()),
            **file_fingerprint(source_path),
            "scope": prior["scope"],
            "occurredAt": prior["occurredAt"],
        }
        regression = {
            "candidateSha256": data.review["candidate"]["sha256"],
            "results": [],
        }
        approval = {
            "checkpoint": "deliver",
            "decision": "approved",
            "candidateIdentityHash": data.review["candidate"]["identityHash"],
            "candidateSha256": data.review["candidate"]["sha256"],
            "dependencyLockSha256": data.review["dependencyLockSha256"],
            "actor": {"type": "user", "id": "creator"},
            "decisionBasis": "prior-exact-master-acceptance-and-current-native-authorization",
            "review": {
                "path": str(data.review_path),
                **file_fingerprint(data.review_path),
                "contentHash": content_hash(data.review),
            },
            "materialization": {
                "path": str(data.kwargs["materialization_path"]),
                **file_fingerprint(data.kwargs["materialization_path"]),
            },
            "regressionResult": {"sha256": content_hash(regression)},
            "approvalId": "candidate-approval-fixture",
        }
        regression_path = workspace.timeline_dir / "external-regression.json"
        if external:
            atomic_write_json(regression_path, regression)
            approval["regressionResult"].update(
                path=str(regression_path),
                fileSha256=file_fingerprint(regression_path)["sha256"],
            )
        if source:
            approval["sourceApprovalRef"] = source_ref
        approval_path = (
            workspace.timeline_dir / "approvals" / f"{approval['approvalId']}.json"
        )
        atomic_write_json(approval_path, approval)
        data.snapshot.update(
            review={
                "artifactId": "deliver-review",
                "sha256": content_hash(data.review),
            },
            regressionResult={
                "artifactId": "regression",
                "sha256": content_hash(regression),
            },
            approval={
                "artifactId": approval["approvalId"],
                "sha256": content_hash(approval),
            },
        )
        monkeypatch.setattr(
            "avo.timeline.approval_service.require_candidate_regression",
            lambda *args, **kwargs: regression,
        )
        service = DeliveryService(workspace)
        service.adopt_existing(**data.kwargs)
        service.approve(actor="creator", reason="exact prior master acceptance")
        data.pipeline = pipeline
        data.service = service
        data.workspace = workspace
        data.approval_path = approval_path
        data.regression_path = regression_path
        data.before = pipeline.run_store.load()
        return data

    return build


def _adopt(data):
    return data.pipeline.adopt_delivery(
        approval_path=data.approval_path,
        actor="avo.pipeline",
        reason="authorized native closure",
    )


def test_adoption_records_one_truthful_jump_and_preserves_history(delivery_adoption):
    data = delivery_adoption()
    result = _adopt(data)
    assert result["mainState"] == "delivered"
    assert result["transitionHistory"][:-1] == data.before["transitionHistory"]
    event = result["transitionHistory"][-1]
    assert event["fromMainState"] == "bmap-draft"
    assert event["toMainState"] == "delivered"
    assert "administrative existing-master adoption" in event["reason"]
    record = result["extensions"]["deliveryAdoption"]["identity"]
    assert record["verifiedCheckpointPolicies"] == [
        "motion-proof",
        "pre-master",
        "deliver",
    ]
    assert record["sourceApprovalRef"]["occurredAt"] == "2026-10-14T12:00:00Z"
    assert record["candidateSha256"] == data.snapshot["candidate"]["sha256"]


def test_same_exact_adoption_is_idempotent(delivery_adoption):
    data = delivery_adoption()
    _adopt(data)
    path = data.workspace.pipeline_run_path
    before = path.read_bytes(), path.stat().st_mtime_ns
    _adopt(data)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("missing", ["bmap", "tracks", "animation", "sync"])
def test_deliver_gate_alone_cannot_satisfy_adoption(delivery_adoption, missing):
    data = delivery_adoption(omit=missing)
    with pytest.raises(GateError, match="missing current evidence"):
        _adopt(data)
    assert data.pipeline.run_store.load() == data.before


def test_adoption_requires_original_exact_creator_acceptance(delivery_adoption):
    data = delivery_adoption(source=False)
    with pytest.raises(ValueError, match="creator acceptance"):
        _adopt(data)
    assert data.pipeline.run_store.load() == data.before


def test_adoption_cannot_clear_a_blocked_side_state(delivery_adoption):
    data = delivery_adoption()
    data.pipeline.enter_blocked(reason="unresolved", blockers=[])
    with pytest.raises(LifecycleError, match="recovery"):
        _adopt(data)


def test_normal_advance_still_cannot_skip_to_delivered(delivery_adoption):
    data = delivery_adoption()
    with pytest.raises(LifecycleError, match="invalid transition"):
        data.pipeline.run_store.advance(
            "delivered",
            TransitionFacts(
                exact_approval=True,
                final_transcript_current=True,
                final_qc_passed=True,
            ),
            actor="fixture",
            reason="must not skip normal stages",
        )


def test_external_regression_artifact_remains_exact(delivery_adoption):
    data = delivery_adoption(external=True)
    assert _adopt(data)["mainState"] == "delivered"


@pytest.mark.parametrize("damage", ["rewrite", "different-path"])
def test_external_regression_cannot_change_bytes_or_path(delivery_adoption, damage):
    data = delivery_adoption(external=True)
    external = data.regression_path
    if damage == "rewrite":
        external.write_text(
            external.read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )
    else:
        alternate = external.with_name("alternate-regression.json")
        alternate.write_bytes(external.read_bytes())
        external = alternate
    with pytest.raises(ValueError, match="external regression"):
        data.pipeline.adopt_delivery(
            approval_path=data.approval_path,
            actor="avo.pipeline",
            reason="authorized native closure",
            regression_path=external,
        )
    assert data.pipeline.run_store.load() == data.before
