"""Explicit human authority preserves automated outcomes and exact provenance."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.timeline.approval_service import (
    _require_human_lineage,
    require_human_final_disposition,
)
from avo.timeline.contracts import content_hash, dependency_lock_hash, file_fingerprint
from avo.timeline.delivery import DeliveryService
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.store import atomic_write_json
from test_candidate_approval import candidate_approval as candidate_fixture


@pytest.fixture
def human_final(tmp_path, monkeypatch):
    data = candidate_fixture.__wrapped__(tmp_path, monkeypatch)
    materialization = json.loads(data.kwargs["materialization_path"].read_text())
    raw = tmp_path / "camera.mkv"
    raw.write_bytes(b"synthetic original")
    source = file_fingerprint(raw)
    materialization["canonicalInputLock"]["rawFingerprints"] = {
        "camera": source["sha256"]
    }
    graph = {
        "canonicalInputLock": materialization["canonicalInputLock"],
        "projectionHash": "d" * 64,
        "nodes": [
            {
                "nodeId": "camera",
                "mediaClass": "source",
                "locator": str(raw),
                "sha256": source["sha256"],
            },
            {
                "nodeId": "output",
                "mediaClass": "master",
                "locator": str(data.master),
                "sha256": materialization["output"]["sha256"],
            },
        ],
        "edges": [{"from": "camera", "to": "output"}],
        "rootIds": ["output"],
    }
    graph["lineageHash"] = content_hash(graph)
    materialization.update(
        pictureLineage=graph,
        pictureLineageHash=graph["lineageHash"],
        projectionHash=graph["projectionHash"],
    )
    materialization["materializationHash"] = content_hash(
        {k: v for k, v in materialization.items() if k != "materializationHash"}
    )
    atomic_write_json(data.kwargs["materialization_path"], materialization)
    compiler = ProofPlanCompiler(data.workspace)
    plan = compiler.load(data.reviewing["proofPlan"]["artifactId"])
    plan["canonicalInputLock"]["source:camera"] = source["sha256"]
    plan["proofPlanHash"] = content_hash(
        {k: v for k, v in plan.items() if k != "proofPlanHash"}
    )
    materialization["proofPlanHash"] = plan["proofPlanHash"]
    materialization["materializationHash"] = content_hash(
        {k: v for k, v in materialization.items() if k != "materializationHash"}
    )
    atomic_write_json(data.kwargs["materialization_path"], materialization)
    atomic_write_json(compiler.path(plan["proofPlanId"]), plan)
    dependencies = {
        **data.review["candidate"]["dependencies"],
        "raw": content_hash(materialization["canonicalInputLock"]["rawFingerprints"]),
        "materialization": materialization["materializationHash"],
        "picture-lineage": graph["lineageHash"],
        "proof-plan": plan["proofPlanHash"],
    }
    prior = tmp_path / "edit" / "prior-approval.json"
    atomic_write_json(
        prior,
        {
            "candidateSha256": materialization["output"]["sha256"],
            "decision": "approved",
            "actor": {"type": "user", "id": "creator"},
            "occurredAt": "2026-10-14T12:00:00Z",
        },
    )
    decision = tmp_path / "edit" / "human-decision.json"
    atomic_write_json(
        decision,
        {
            "authority": "human-final",
            "decision": "approved",
            "actor": {"type": "user", "id": "creator"},
            "candidateSha256": materialization["output"]["sha256"],
            "dependencyLockSha256": dependency_lock_hash(dependencies),
            "automatedReviewDisposition": "superseded-by-explicit-human-approval",
            "instruction": "Human review is absolute above automated review; approved.",
        },
    )
    reports = {}
    for name, status in (
        ("qc", "skipped"),
        ("transcript-analysis", "fail"),
        ("watch", "interrupted"),
    ):
        path = tmp_path / "edit" / f"{name}.json"
        atomic_write_json(
            path,
            {"candidateSha256": materialization["output"]["sha256"], "status": status},
        )
        reports[name] = path
    data.human_kwargs = {
        "candidate": data.master,
        "dependencies": dependencies,
        "materialization_path": data.kwargs["materialization_path"],
        "proof_plan_path": compiler.path(plan["proofPlanId"]),
        "decision_ref": {"path": str(decision), **file_fingerprint(decision)},
        "source_approval_ref": {"path": str(prior), **file_fingerprint(prior)},
        "automated_evidence_paths": reports,
        "actor": "creator",
        "reason": "Explicit human final disposition of unchanged master.",
    }
    data.human_materialization = materialization
    return data


def _validate(data, path):
    return require_human_final_disposition(
        data.workspace,
        path,
        candidate=data.master,
        fingerprint=file_fingerprint(data.master),
        materialization=data.human_materialization,
        dependencies=data.human_kwargs["dependencies"],
    )


def test_human_final_preserves_failed_and_skipped_results_without_fake_snapshot(
    human_final,
):
    data = human_final
    before = data.pipeline.active_candidate_snapshot()
    original = {
        name: path.read_bytes()
        for name, path in data.human_kwargs["automated_evidence_paths"].items()
    }
    result = data.service.decide_human_final(**data.human_kwargs)
    assert {
        name: ref["status"] for name, ref in result["automatedEvidence"].items()
    } == {"qc": "skipped", "transcript-analysis": "fail", "watch": "interrupted"}
    assert result["regressionPassAsserted"] is False
    assert result["automatedOutcomesReclassified"] is False
    assert data.pipeline.active_candidate_snapshot() == before
    assert (
        _validate(data, result["path"])["dispositionHash"] == result["dispositionHash"]
    )
    assert data.service.decide_human_final(**data.human_kwargs) == result
    assert original == {
        name: path.read_bytes()
        for name, path in data.human_kwargs["automated_evidence_paths"].items()
    }


@pytest.mark.parametrize(
    "damage",
    [
        "ordinary-approval",
        "wrong-decision-candidate",
        "wrong-decision-lock",
        "stale-head",
        "report-other-candidate",
        "changed-decision",
        "changed-report",
        "changed-source",
        "changed-master",
    ],
)
def test_human_final_rejects_wrong_authority_or_changed_inputs(human_final, damage):
    data = human_final
    decision_path = Path(data.human_kwargs["decision_ref"]["path"])
    if damage in {
        "ordinary-approval",
        "wrong-decision-candidate",
        "wrong-decision-lock",
    }:
        decision = json.loads(decision_path.read_text())
        key, value = {
            "ordinary-approval": ("authority", "ordinary"),
            "wrong-decision-candidate": ("candidateSha256", "0" * 64),
            "wrong-decision-lock": ("dependencyLockSha256", "0" * 64),
        }[damage]
        decision[key] = value
        atomic_write_json(decision_path, decision)
        data.human_kwargs["decision_ref"] = {
            "path": str(decision_path),
            **file_fingerprint(decision_path),
        }
    elif damage == "stale-head":
        data.heads["tracks"] = "0" * 64
    elif damage == "report-other-candidate":
        path = data.human_kwargs["automated_evidence_paths"]["watch"]
        atomic_write_json(path, {"status": "interrupted", "candidateSha256": "0" * 64})
    if damage.startswith("changed-"):
        result = data.service.decide_human_final(**data.human_kwargs)
        path = {
            "changed-decision": decision_path,
            "changed-report": data.human_kwargs["automated_evidence_paths"]["watch"],
            "changed-source": Path(data.human_kwargs["source_approval_ref"]["path"]),
            "changed-master": data.master,
        }[damage]
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(ValueError):
            _validate(data, result["path"])
    else:
        with pytest.raises(ValueError):
            data.service.decide_human_final(**data.human_kwargs)


def test_human_final_adoption_and_archive_are_current_human_decisions(
    human_final, monkeypatch
):
    data = human_final
    disposition = data.service.decide_human_final(**data.human_kwargs)
    service = DeliveryService(data.workspace)
    service.adopt_existing(
        master=data.master,
        dependencies=data.human_kwargs["dependencies"],
        materialization=data.human_materialization,
        materialization_path=data.human_kwargs["materialization_path"],
        transcript_artifacts=data.sidecars,
        review_path=None,
        human_final_disposition_path=Path(disposition["path"]),
    )
    service.approve(actor="creator", reason="Human final decision")
    project = json.loads(data.workspace.project_path.read_text())
    project["cleanup"] = {"preservePaths": ["edit"]}
    atomic_write_json(data.workspace.project_path, project)
    for name in data.heads:
        monkeypatch.setattr(
            data.workspace,
            "require_active",
            lambda key: {"activeState": "valid", "headRevisionId": key + "-r0001"},
        )
    before = data.pipeline.run_store.load()
    result = data.pipeline.adopt_human_final_delivery(
        human_final_disposition_path=Path(disposition["path"]),
        actor="creator",
        reason="Approved human final preservation",
        archive=True,
    )
    assert result["mainState"] == "archived"
    assert "activeCandidateSnapshot" not in result["activeRefs"]
    assert (
        result["transitionHistory"][: len(before["transitionHistory"])]
        == before["transitionHistory"]
    )
    assert len(result["transitionHistory"]) == len(before["transitionHistory"]) + 2
    archive = result["extensions"]["humanFinalArchive"]
    assert (
        archive["byteVerificationAsserted"] is False
        and archive["cleanupExecuted"] is False
    )
    assert (
        archive["preservationVerification"]
        == "recorded-separately-in-final-preservation-receipt"
    )
    assert (
        result["extensions"]["deliveryAdoption"]["identity"]["regressionPassAsserted"]
        is False
    )
    assert (
        data.pipeline.adopt_human_final_delivery(
            human_final_disposition_path=Path(disposition["path"]),
            actor="creator",
            reason="Approved human final preservation",
            archive=True,
        )
        == result
    )
    assert not (
        data.workspace.raw_dir / "edit/cleanup/preservation-result.json"
    ).exists()


def test_human_lineage_uses_native_picture_and_audiovisual_hash_fields(human_final):
    data = human_final
    materialization = deepcopy(data.human_materialization)
    picture = materialization["pictureLineage"]
    picture["pictureLineageHash"] = picture.pop("lineageHash")
    audiovisual = deepcopy(picture)
    audiovisual.pop("pictureLineageHash")
    audiovisual["nodes"][-1]["audioCarrying"] = True
    audiovisual["lineageHash"] = content_hash(audiovisual)
    materialization["audiovisualLineage"] = audiovisual
    materialization["audiovisualLineageHash"] = audiovisual["lineageHash"]
    _require_human_lineage(materialization, data.master, file_fingerprint(data.master))
    picture["pictureLineageHash"] = "0" * 64
    with pytest.raises(ValueError, match="lineage"):
        _require_human_lineage(
            materialization, data.master, file_fingerprint(data.master)
        )


@pytest.mark.parametrize("damage", ["lineage", "decision"])
def test_human_metadata_preflight_fails_before_reading_candidate(
    human_final, monkeypatch, damage
):
    data = human_final
    import avo.timeline.approval_service as approvals

    original = approvals.file_fingerprint

    def no_master_read(path):
        if Path(path).resolve() == data.master.resolve():
            pytest.fail("invalid metadata read the candidate before preflight")
        return original(path)

    monkeypatch.setattr(approvals, "file_fingerprint", no_master_read)
    if damage == "lineage":
        materialization = data.human_materialization
        materialization["pictureLineage"]["lineageHash"] = "0" * 64
        materialization["materializationHash"] = content_hash(
            {
                key: value
                for key, value in materialization.items()
                if key != "materializationHash"
            }
        )
        atomic_write_json(data.human_kwargs["materialization_path"], materialization)
        data.human_kwargs["dependencies"]["materialization"] = materialization[
            "materializationHash"
        ]
    else:
        data.human_kwargs["decision_ref"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        data.service.decide_human_final(**data.human_kwargs)
