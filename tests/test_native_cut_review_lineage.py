from copy import deepcopy

import pytest

from avo.cli import _materialization_dependencies
from avo.timeline.approval_service import (
    _decision_materialization_lock,
    native_cut_dependencies,
    require_candidate_regression,
    require_native_cut_materialization,
)
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.materialize import (
    canonical_proof_media_inputs,
    materialize_proof_plan,
    render_proof_microproofs,
)
from avo.timeline.proof_plan import ProofPlanCompiler, ProofPlanError
from avo.timeline.store import atomic_write_json
from test_initial_cut_proof_plan import setup_cut


class Renderer:
    def proof_tool_readiness(self, plan):
        return {"proof-plan-executor": True, "ffmpeg": True, "hyperframes": True}

    def render_proof_plan(self, plan, output, *, window):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exact source-bound native candidate")
        return {"output": file_fingerprint(output), "graphHash": "a" * 64}


def native_materialization(tmp_path):
    workspace, request, contract, _ = setup_cut(tmp_path)
    sync = workspace.store("sync-map")
    revision = sync.revision(sync.load_index()["headRevisionId"])
    sync.record_decision(
        decision="approved",
        revision_id=revision["revisionId"],
        revision_hash=revision["contentHash"],
        candidate_hash=revision["contentHash"],
        dependency_hashes={"sync-map": revision["contentHash"]},
        actor="creator",
        checkpoint="sync-map",
        scope="exact-sync",
        reason="verified fixture",
        evidence_bundle_hash="a" * 64,
    )
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.compile(request, regression_contract=contract)
    inputs = canonical_proof_media_inputs(workspace, plan)
    gate = render_proof_microproofs(
        workspace=workspace,
        proof_plan=plan,
        media_inputs=inputs,
        render_port=Renderer(),
    )
    record = materialize_proof_plan(
        workspace=workspace,
        proof_plan=plan,
        microproof_gate=gate,
        media_inputs=inputs,
        render_port=Renderer(),
    )
    record.pop("path")
    return workspace, plan, record, gate


def test_native_cut_has_exact_cli_and_approval_dependencies_without_later_maps(
    tmp_path,
):
    workspace, plan, record, _ = native_materialization(tmp_path)
    candidate = plan["output"]["path"]
    dependencies = require_native_cut_materialization(workspace, record, candidate)
    assert dependencies == _materialization_dependencies(record)
    assert dependencies["proof-plan"] == plan["proofPlanHash"]
    revision = workspace.store("cmap").revision(
        workspace.store("cmap").load_index()["headRevisionId"]
    )
    lock = _decision_materialization_lock(workspace, record, revision, dependencies)
    assert lock["cmapRevisionHash"] == revision["contentHash"]
    for name in ("bmap", "tracks", "animation"):
        assert workspace.store(name).load_index()["headRevisionId"] is None


@pytest.mark.parametrize(
    "field", ["proofPlanHash", "microproofGateHash", "canonicalInputLock"]
)
def test_rehashed_counterfeit_native_record_cannot_replace_plan_or_gate(
    tmp_path, field
):
    workspace, plan, record, _ = native_materialization(tmp_path)
    altered = deepcopy(record)
    altered[field] = {} if field == "canonicalInputLock" else "0" * 64
    altered["materializationHash"] = content_hash(
        {k: v for k, v in altered.items() if k != "materializationHash"}
    )
    with pytest.raises((ValueError, RuntimeError)):
        require_native_cut_materialization(workspace, altered, plan["output"]["path"])


def test_native_review_rechecks_absence_and_original_bytes(tmp_path):
    workspace, plan, record, _ = native_materialization(tmp_path)
    index = workspace.store("bmap").load_index()
    index["updatedAt"] = "2026-10-05T15:00:00Z"
    atomic_write_json(workspace.store("bmap").path, index)
    with pytest.raises(ProofPlanError, match="absence"):
        require_native_cut_materialization(workspace, record, plan["output"]["path"])


def test_native_review_rejects_changed_source_or_gate(tmp_path):
    workspace, plan, record, gate = native_materialization(tmp_path)
    (workspace.raw_dir / "camera.mkv").write_bytes(b"changed source")
    with pytest.raises(ProofPlanError, match="source"):
        require_native_cut_materialization(workspace, record, plan["output"]["path"])
    (workspace.raw_dir / "camera.mkv").write_bytes(b"fingerprinted raw source")
    gate.pop("path")
    gate["results"][0]["status"] = "fail"
    path = (
        workspace.timeline_dir
        / "microproofs"
        / plan["proofPlanId"]
        / f"gate-{gate['gateHash'][:12]}.json"
    )
    atomic_write_json(path, gate)
    with pytest.raises(RuntimeError, match="modified"):
        require_native_cut_materialization(workspace, record, plan["output"]["path"])


def test_native_later_checkpoint_cannot_enter_cut_review(tmp_path):
    _, _, record, _ = native_materialization(tmp_path)
    record["checkpoint"] = "pre-master"
    record["materializationHash"] = content_hash(
        {k: v for k, v in record.items() if k != "materializationHash"}
    )
    with pytest.raises(ValueError, match="explicit cut-proof"):
        native_cut_dependencies(record)


def test_native_qc_validates_plan_instead_of_legacy_projection(tmp_path, monkeypatch):
    from avo.adapters.qc import cut_proof

    workspace, plan, record, _ = native_materialization(tmp_path)
    dependencies = native_cut_dependencies(record)
    calls = []
    monkeypatch.setattr(
        cut_proof, "verify_projection", lambda _: pytest.fail("legacy projection used")
    )
    monkeypatch.setattr(
        cut_proof, "_require_current_cut_heads", lambda *args: calls.append(args)
    )
    cut_proof._require_cut_lineage(
        workspace, record, plan["output"]["path"], dependencies
    )
    assert len(calls) == 1
    dependencies["microproof-gate"] = "0" * 64
    with pytest.raises(ValueError, match="not exact"):
        cut_proof._require_cut_lineage(
            workspace, record, plan["output"]["path"], dependencies
        )


def test_rehashed_graph_under_existing_plan_identity_is_rejected(tmp_path):
    workspace, plan, record, _ = native_materialization(tmp_path)
    plan["validationPlan"]["fullReview"] = ["technical-qc"]
    plan["proofPlanHash"] = content_hash(
        {k: v for k, v in plan.items() if k != "proofPlanHash"}
    )
    atomic_write_json(ProofPlanCompiler(workspace).path(plan["proofPlanId"]), plan)
    record["proofPlanHash"] = plan["proofPlanHash"]
    record["materializationHash"] = content_hash(
        {k: v for k, v in record.items() if k != "materializationHash"}
    )
    with pytest.raises(ValueError, match="identity does not match"):
        require_native_cut_materialization(workspace, record, plan["output"]["path"])


def test_default_readiness_uses_materialization_boundary(monkeypatch):
    from avo.adapters.media import timeline_render
    from avo.timeline.materialize import default_proof_readiness

    plans = []

    class Probe:
        def proof_tool_readiness(self, plan):
            plans.append(plan)
            return {"ffmpeg": True}

        def render_proof_plan(self, *args, **kwargs):
            pytest.fail("readiness probe must not render")

    monkeypatch.setattr(timeline_render, "TimelineRenderAdapter", Probe)
    plan = {"proofPlanId": "probe-only"}
    assert default_proof_readiness(plan) == {
        "ffmpeg": True,
        "proof-plan-executor": True,
    }
    assert plans == [plan]


def _native_regression_review(tmp_path, monkeypatch):
    workspace, plan, record, _ = native_materialization(tmp_path)
    heads = {
        name: workspace.store(name).revision(
            workspace.require_active(name)["headRevisionId"]
        )["contentHash"]
        for name in ("cmap", "sync-map")
    }
    monkeypatch.setattr(
        workspace, "active_dependency_snapshot", lambda: heads, raising=False
    )
    snapshot = {
        "proofPlan": {
            "artifactId": plan["proofPlanId"],
            "sha256": plan["proofPlanHash"],
        },
        "iterationId": plan["iterationId"],
    }
    review = {
        "evidence": [],
        "candidate": {
            "sha256": record["output"]["sha256"],
            "dependencies": native_cut_dependencies(record),
        },
    }
    result = {
        "contractHash": plan["regressionContract"]["contractHash"],
        "candidateSha256": record["output"]["sha256"],
        "results": [],
        "exceptions": [],
        "summary": {},
    }
    path = tmp_path / "regression-result.json"
    atomic_write_json(path, result)
    return workspace, snapshot, review, record, path, result


def test_native_cut_regression_accepts_its_source_alias_lock(tmp_path, monkeypatch):
    workspace, snapshot, review, record, path, expected = _native_regression_review(
        tmp_path, monkeypatch
    )
    assert "rawFingerprints" not in record["canonicalInputLock"]
    assert (
        require_candidate_regression(
            workspace, snapshot, review, path, materialization=record
        )
        == expected
    )


@pytest.mark.parametrize("damage", ["raw-review", "source-review", "source-lock"])
def test_native_cut_regression_rejects_stale_source_bindings(
    tmp_path, monkeypatch, damage
):
    workspace, snapshot, review, record, path, _ = _native_regression_review(
        tmp_path, monkeypatch
    )
    if damage == "raw-review":
        review["candidate"]["dependencies"]["raw"] = "0" * 64
    elif damage == "source-review":
        review["candidate"]["dependencies"]["source:camera"] = "0" * 64
    else:
        record["canonicalInputLock"]["source:camera"] = "0" * 64
        record["materializationHash"] = content_hash(
            {k: v for k, v in record.items() if k != "materializationHash"}
        )
        review["candidate"]["dependencies"] = native_cut_dependencies(record)
    with pytest.raises((ValueError, RuntimeError)):
        require_candidate_regression(
            workspace, snapshot, review, path, materialization=record
        )
