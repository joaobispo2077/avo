"""Non-cut approvals bind actual reviews and preserve candidate lifecycle history."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from avo.timeline.approval_service import ApprovalService, require_candidate_regression
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.review import CHECKPOINT_POLICIES, candidate_identity
from avo.timeline.store import atomic_write_json
from avo.timeline.workspace import TimelineWorkspace
from test_delivery_adoption import adoption as adoption_fixture


@pytest.fixture
def candidate_approval(tmp_path, monkeypatch):
    original_init = TimelinePipeline.__init__
    original_active = TimelinePipeline.active_candidate_snapshot
    data = adoption_fixture.__wrapped__(tmp_path, monkeypatch)
    monkeypatch.setattr(TimelinePipeline, "__init__", original_init)
    monkeypatch.setattr(TimelinePipeline, "active_candidate_snapshot", original_active)
    data.service.workspace.pipeline_run_path.unlink()
    project = {
        "schemaVersion": "1.0.0",
        "provider": "fixture",
        "videoId": "candidate-approval",
        "rawDir": str(tmp_path),
    }
    project_path = tmp_path / "avo.project.json"
    atomic_write_json(project_path, project)
    workspace = TimelineWorkspace.from_project(project_path)
    workspace.initialize()
    monkeypatch.setattr(workspace, "active_dependency_snapshot", lambda: data.heads)
    monkeypatch.setattr(
        workspace, "require_active", lambda name: {"activeState": "valid"}
    )
    monkeypatch.setattr(workspace, "notify_editlog", dict)
    pipeline = TimelinePipeline(workspace)
    materialization = data.kwargs["materialization"]
    contract_body = {
        "contractId": "contract-fixture",
        "ledgerHash": "8" * 64,
        "iterationId": "iteration-fixture",
        "obligations": [{"decisionId": "fixture"}],
        "historicalRiskWindows": [],
        "conflicts": [],
    }
    contract = {**contract_body, "contractHash": content_hash(contract_body)}
    plan_body = {
        "schemaVersion": "1.0.0",
        "proofPlanId": "proof-plan-fixture",
        "iterationId": "iteration-fixture",
        "canonicalInputLock": dict(data.heads),
        "regressionContract": contract,
        "renderProfile": "master",
        "output": {
            "path": str(data.master),
            "width": 640,
            "height": 360,
            "frameRate": {"num": 60, "den": 1},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "videoCodec": "h264",
            "audioCodec": "aac",
        },
        "capabilityResolution": [],
        "implementationRefs": [],
        "videoGraph": {"operations": []},
        "audioGraph": {
            "sampleRate": 48000,
            "nodes": [],
            "operations": [],
            "singleFinalEncode": True,
        },
        "events": [],
        "validationPlan": {
            "preflight": [],
            "microproof": [],
            "fullReview": [],
            "historicalRegression": [],
        },
        "visionReviewPlanRef": None,
        "lineagePolicy": {
            "allowedMediaClasses": [],
            "prohibitedMediaClasses": [
                "proof",
                "preview",
                "proxy",
                "master",
                "delivery",
            ],
            "recursive": True,
        },
        "producer": {"name": "fixture", "version": "1", "compiler": "fixture"},
    }
    plan = {**plan_body, "proofPlanHash": content_hash(plan_body)}
    atomic_write_json(ProofPlanCompiler(workspace).path(plan["proofPlanId"]), plan)
    materialization["proofPlanHash"] = plan["proofPlanHash"]
    materialization["materializationHash"] = content_hash(
        {
            key: value
            for key, value in materialization.items()
            if key != "materializationHash"
        }
    )
    atomic_write_json(data.kwargs["materialization_path"], materialization)
    dependencies = data.review["candidate"]["dependencies"]
    dependencies["proof-plan"] = plan["proofPlanHash"]
    dependencies["materialization"] = materialization["materializationHash"]
    data.review["candidate"] = candidate_identity(data.master, dependencies, "master")
    data.review["dependencyLockSha256"] = content_hash(dependencies)
    for evidence in data.review["evidence"]:
        evidence["candidateIdentityHash"] = data.review["candidate"]["identityHash"]
        evidence["dependencyLockSha256"] = data.review["dependencyLockSha256"]
        evidence["dependencyHashes"] = dependencies
    rendered = pipeline.record_candidate_snapshot(
        state="rendered",
        candidate=data.master,
        iteration_id="iteration-fixture",
        proof_plan=plan,
        materialization=materialization,
        expected_active_snapshot_hash=None,
    )
    reviewing = pipeline.record_candidate_snapshot(
        state="reviewing",
        candidate=data.master,
        iteration_id="iteration-fixture",
        proof_plan=plan,
        materialization=materialization,
        transcript={
            "fingerprint": file_fingerprint(data.sidecars["json"]),
            "sourceSha256": materialization["output"]["sha256"],
        },
        expected_active_snapshot_hash=rendered["snapshotHash"],
    )
    regression = {
        "contractHash": contract["contractHash"],
        "candidateSha256": materialization["output"]["sha256"],
        "results": [
            {
                "obligationId": "fixture",
                "status": "preserved",
                "evidenceRefs": [
                    {
                        "path": str(data.sidecars["json"]),
                        "sha256": file_fingerprint(data.sidecars["json"])["sha256"],
                    }
                ],
            }
        ],
        "exceptions": [],
        "summary": {"status": "pass"},
    }
    data.workspace = workspace
    data.pipeline = pipeline
    data.reviewing = reviewing
    data.regression = regression
    data.service = ApprovalService(workspace)
    data.kwargs = {
        "checkpoint": "deliver",
        "review_path": data.review_path,
        "materialization_path": data.kwargs["materialization_path"],
        "actor": "fixture-creator",
        "reason": "synthetic review fixture, not human footage",
    }
    data.regression_path = tmp_path / "edit" / "review" / "regression.json"
    return data


def _review(data, checkpoint="deliver", *, with_regression=True):
    data.review["checkpoint"] = checkpoint
    data.kwargs["checkpoint"] = checkpoint
    template = data.review["evidence"][0]
    by_kind = {item["kind"]: item for item in data.review["evidence"]}
    evidence = []
    for kind in sorted(CHECKPOINT_POLICIES[checkpoint]["required"]):
        item = copy.deepcopy(by_kind.get(kind, template))
        item["kind"] = kind
        item["evidenceId"] = f"{checkpoint}-{kind}"
        if kind == "lineage" and with_regression:
            item["regressionResult"] = data.regression
        evidence.append(item)
    data.review["evidence"] = evidence
    atomic_write_json(data.review_path, data.review)


@pytest.mark.parametrize("checkpoint", ["motion-proof", "pre-master", "deliver"])
def test_decide_candidate_binds_real_review_without_advancing_pipeline(
    candidate_approval, checkpoint
):
    data = candidate_approval
    _review(data, checkpoint)
    before = data.pipeline.run_store.load()["mainState"]
    approval = data.service.decide_candidate(**data.kwargs)
    assert approval["decision"] == "approved"
    assert approval["checkpoint"] == checkpoint
    assert approval["candidateSha256"] == data.review["candidate"]["sha256"]
    assert approval["actor"] == {"type": "user", "id": "fixture-creator"}
    persisted = json.loads(Path(approval["path"]).read_text(encoding="utf-8"))
    assert persisted["decidedAt"] == approval["decidedAt"]
    assert data.pipeline.run_store.load()["mainState"] == before
    snapshot = data.pipeline.active_candidate_snapshot()
    assert snapshot["state"] == "approved"
    assert snapshot["review"]["sha256"] == content_hash(data.review)
    assert snapshot["regressionResult"]["sha256"] == content_hash(data.regression)
    assert snapshot["approval"]["sha256"] == content_hash(persisted)


def test_checkpoint_approval_can_preserve_reviewing_until_final_checkpoint(
    candidate_approval,
):
    data = candidate_approval
    for checkpoint in ("motion-proof", "pre-master"):
        _review(data, checkpoint)
        approval = data.service.decide_candidate(**data.kwargs, finalize_snapshot=False)
        assert Path(approval["path"]).is_file()
        assert data.pipeline.active_candidate_snapshot() == data.reviewing
    _review(data, "deliver")
    data.service.decide_candidate(**data.kwargs)
    assert data.pipeline.active_candidate_snapshot()["state"] == "approved"


@pytest.mark.parametrize(
    "damage",
    [
        "no-regression",
        "wrong-regression",
        "unresolved",
        "regressed",
        "stale-artifact",
        "blocked-review",
        "missing-watch",
        "incomplete-watch",
        "stale-head",
        "wrong-size",
        "wrong-identity",
        "wrong-lock",
    ],
)
def test_candidate_approval_fails_closed_without_complete_evidence(
    candidate_approval, damage
):
    data = candidate_approval
    if damage == "wrong-regression":
        data.regression["candidateSha256"] = "0" * 64
    elif damage in {"unresolved", "regressed"}:
        data.regression["results"][0]["status"] = damage
    elif damage == "stale-artifact":
        data.regression["results"][0]["evidenceRefs"][0]["sha256"] = "0" * 64
    elif damage == "blocked-review":
        data.review["state"] = "blocked"
    elif damage == "stale-head":
        data.heads["tracks"] = "0" * 64
    elif damage == "wrong-size":
        data.review["candidate"]["byteSize"] += 1
    elif damage == "wrong-identity":
        data.review["candidate"]["identityHash"] = "0" * 64
    elif damage == "wrong-lock":
        data.review["dependencyLockSha256"] = "0" * 64
    _review(data, with_regression=damage != "no-regression")
    if damage == "missing-watch":
        data.review["evidence"] = [
            item for item in data.review["evidence"] if item["kind"] != "watch"
        ]
    elif damage == "incomplete-watch":
        next(item for item in data.review["evidence"] if item["kind"] == "watch")[
            "coverage"
        ]["observedFrames"] = [0]
    atomic_write_json(data.review_path, data.review)
    with pytest.raises(ValueError):
        data.service.decide_candidate(**data.kwargs)
    assert data.pipeline.active_candidate_snapshot() == data.reviewing
    assert not list((data.workspace.timeline_dir / "approvals").glob("*.json"))


def test_candidate_approval_accepts_exact_external_regression(candidate_approval):
    data = candidate_approval
    _review(data, with_regression=False)
    atomic_write_json(data.regression_path, data.regression)
    result = data.service.decide_candidate(
        **data.kwargs, regression_path=data.regression_path
    )
    assert result["regressionResult"]["sha256"] == content_hash(data.regression)


def test_prior_approval_reference_is_exact_and_never_backdates(candidate_approval):
    data = candidate_approval
    _review(data)
    prior = data.workspace.raw_dir / "edit" / "review" / "creator-approval.json"
    atomic_write_json(
        prior,
        {
            "candidateSha256": data.review["candidate"]["sha256"],
            "decidedAt": "2026-10-14T12:00:00Z",
            "decision": "approved",
            "actor": {"type": "user", "id": "fixture-creator"},
        },
    )
    before = prior.read_bytes()
    result = data.service.decide_candidate(
        **data.kwargs,
        source_approval_ref={"path": str(prior), **file_fingerprint(prior)},
    )
    assert result["sourceApprovalRef"]["sha256"] == file_fingerprint(prior)["sha256"]
    assert result["decidedAt"] != "2026-10-14T12:00:00Z"
    assert prior.read_bytes() == before


def test_prior_approval_hash_cannot_be_guessed(candidate_approval):
    data = candidate_approval
    _review(data)
    prior = data.workspace.raw_dir / "edit" / "review" / "creator-approval.json"
    atomic_write_json(prior, {"candidateSha256": data.review["candidate"]["sha256"]})
    with pytest.raises(ValueError, match="source approval"):
        data.service.decide_candidate(
            **data.kwargs, source_approval_ref={"path": str(prior), "sha256": "0" * 64}
        )
    assert data.pipeline.active_candidate_snapshot() == data.reviewing


@pytest.mark.parametrize(
    "damage",
    ["contract", "missing-obligation", "duplicate-obligation", "empty-evidence"],
)
def test_candidate_approval_requires_exact_plan_regression_coverage(
    candidate_approval, damage
):
    data = candidate_approval
    if damage == "contract":
        data.regression["contractHash"] = "0" * 64
    elif damage == "missing-obligation":
        data.regression["results"] = []
    elif damage == "duplicate-obligation":
        data.regression["results"].append(copy.deepcopy(data.regression["results"][0]))
    else:
        data.regression["results"][0]["evidenceRefs"] = []
    _review(data)
    with pytest.raises(ValueError, match="regression"):
        data.service.decide_candidate(**data.kwargs)
    assert data.pipeline.active_candidate_snapshot() == data.reviewing


def test_candidate_approval_repetition_is_exactly_idempotent(candidate_approval):
    data = candidate_approval
    _review(data)
    first = data.service.decide_candidate(**data.kwargs)
    snapshot = data.pipeline.active_candidate_snapshot()
    repeated = data.service.decide_candidate(**data.kwargs)
    assert repeated == first
    assert data.pipeline.active_candidate_snapshot() == snapshot
    assert len(list((data.workspace.timeline_dir / "approvals").glob("*.json"))) == 1


def test_candidate_approval_preserves_existing_needs_human_binding_ids(
    candidate_approval,
):
    data = candidate_approval
    _review(data)
    previous = data.pipeline.active_candidate_snapshot()
    needs_human = data.pipeline.record_candidate_snapshot(
        state="needs-human",
        candidate=previous["candidate"],
        iteration_id=previous["iterationId"],
        proof_plan={**previous["proofPlan"], "iterationId": previous["iterationId"]},
        materialization={
            **previous["materialization"],
            "candidateSha256": previous["candidate"]["sha256"],
        },
        transcript={
            "fingerprint": previous["transcript"],
            "sourceSha256": previous["candidate"]["sha256"],
        },
        review={
            "artifactId": "native-review-original-id",
            "sha256": content_hash(data.review),
            "candidateSha256": previous["candidate"]["sha256"],
            "proofPlanSha256": previous["proofPlan"]["sha256"],
        },
        regression_result={
            "artifactId": "native-regression-original-id",
            "sha256": content_hash(data.regression),
            "candidateSha256": previous["candidate"]["sha256"],
        },
        expected_active_snapshot_hash=previous["snapshotHash"],
    )
    data.service.decide_candidate(**data.kwargs)
    approved = data.pipeline.active_candidate_snapshot()
    assert approved["review"] == needs_human["review"]
    assert approved["regressionResult"] == needs_human["regressionResult"]


def _replace_candidate_plan_lock(data, lock, monkeypatch, *, raw=None):
    compiler = ProofPlanCompiler(data.workspace)
    plan = compiler.load(data.reviewing["proofPlan"]["artifactId"])
    plan["canonicalInputLock"] = lock
    plan["proofPlanHash"] = content_hash(
        {key: value for key, value in plan.items() if key != "proofPlanHash"}
    )
    atomic_write_json(compiler.path(plan["proofPlanId"]), plan)
    materialization = json.loads(data.kwargs["materialization_path"].read_text())
    materialization["proofPlanHash"] = plan["proofPlanHash"]
    if raw is not None:
        materialization["canonicalInputLock"]["rawFingerprints"] = raw
        data.review["candidate"]["dependencies"]["raw"] = content_hash(raw)
    materialization["materializationHash"] = content_hash(
        {
            key: value
            for key, value in materialization.items()
            if key != "materializationHash"
        }
    )
    atomic_write_json(data.kwargs["materialization_path"], materialization)
    dependencies = data.review["candidate"]["dependencies"]
    dependencies.update(
        {
            "proof-plan": plan["proofPlanHash"],
            "materialization": materialization["materializationHash"],
        }
    )
    data.review["candidate"] = candidate_identity(data.master, dependencies, "master")
    data.review["dependencyLockSha256"] = content_hash(dependencies)
    for evidence in data.review["evidence"]:
        evidence["candidateIdentityHash"] = data.review["candidate"]["identityHash"]
        evidence["dependencyLockSha256"] = data.review["dependencyLockSha256"]
        evidence["dependencyHashes"] = dependencies
    data.reviewing["proofPlan"]["sha256"] = plan["proofPlanHash"]
    data.reviewing["materialization"]["sha256"] = materialization["materializationHash"]
    monkeypatch.setattr(
        TimelinePipeline, "active_candidate_snapshot", lambda self: data.reviewing
    )
    _review(data)
    return materialization


@pytest.mark.parametrize("owner", ["cmap", "sync-map", "bmap", "tracks", "animation"])
def test_candidate_approval_rejects_self_consistent_stale_plan_owner(
    candidate_approval, monkeypatch, owner
):
    data = candidate_approval
    lock = {**data.heads, owner: "0" * 64}
    _replace_candidate_plan_lock(data, lock, monkeypatch)
    with pytest.raises(ValueError, match="proof.plan.*canonical"):
        data.service.decide_candidate(**data.kwargs, finalize_snapshot=False)
    assert not list((data.workspace.timeline_dir / "approvals").glob("*.json"))


@pytest.mark.parametrize(
    "damage",
    [
        "missing-owner",
        "conflicting-alias",
        "stale-source",
        "stale-raw-review",
        "missing-review-source",
        "conflicting-review-source",
    ],
)
def test_regression_revalidation_rejects_stale_plan_inputs(
    candidate_approval, monkeypatch, damage
):
    data = candidate_approval
    raw = {"camera": "9" * 64}
    lock = {**data.heads, "source:camera": raw["camera"]}
    if damage == "missing-owner":
        lock.pop("animation")
    elif damage == "conflicting-alias":
        lock["tracksRevisionHash"] = "0" * 64
    elif damage == "stale-source":
        lock["source:camera"] = "0" * 64
    materialization = _replace_candidate_plan_lock(data, lock, monkeypatch, raw=raw)
    if damage == "stale-raw-review":
        data.review["candidate"]["dependencies"]["raw"] = "0" * 64
    elif damage == "missing-review-source":
        data.review["candidate"]["dependencies"]["source:external"] = "7" * 64
    elif damage == "conflicting-review-source":
        data.review["candidate"]["dependencies"]["source:camera"] = "0" * 64
    with pytest.raises(ValueError, match="proof.plan.*(canonical|source|raw)"):
        require_candidate_regression(
            data.workspace,
            data.reviewing,
            data.review,
            materialization=materialization,
        )


@pytest.mark.parametrize("legacy_plan", [False, True])
def test_regression_plan_supports_assembly_aliases_and_extra_asset_sources(
    candidate_approval, monkeypatch, legacy_plan
):
    data = candidate_approval
    raw = {"camera": "9" * 64, "unused-camera": "8" * 64}
    lock = {
        **data.heads,
        "source:camera": raw["camera"],
        "source:generated-asset": "7" * 64,
    }
    aliases = {
        "cmap": "cmapRevisionHash",
        "sync-map": "syncRevisionHash",
        "bmap": "bmapRevisionHash",
        "tracks": "tracksRevisionHash",
    }
    if legacy_plan:
        for owner, alias in aliases.items():
            lock[alias] = lock.pop(owner)
    materialization = _replace_candidate_plan_lock(data, lock, monkeypatch, raw=raw)
    assembly_lock = materialization["canonicalInputLock"]
    for owner, alias in aliases.items():
        assembly_lock[alias] = assembly_lock.pop(owner)
    result = require_candidate_regression(
        data.workspace,
        data.reviewing,
        data.review,
        materialization=materialization,
    )
    assert result == data.regression
