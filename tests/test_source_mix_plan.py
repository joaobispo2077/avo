"""Imported source mix controls are compiled once without changing the cut."""

from copy import deepcopy

import pytest

from avo.timeline.contracts import document_hash_excluding, file_fingerprint
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.proof_plan import ProofPlanCompiler, ProofPlanError
from tests.test_import_audio_tail import tail_snapshot
from tests.test_proof_plan import regression_contract, workspace_with_heads


def mix_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "avo.timeline.import_evidence.verify_import_origin", lambda *_args: None
    )
    workspace = workspace_with_heads(tmp_path)
    source = tmp_path / "microphone.wav"
    source.write_bytes(b"original source fixture")
    snapshot = tail_snapshot()
    snapshot["sources"][0].update(
        locator=str(source), fingerprint=file_fingerprint(source)
    )
    placement = snapshot["layout"]["placements"][0]
    placement.update(gainDb=10, audioPeakCeilingDbfs=-4.5)
    workspace.store("cmap").append_revision(
        snapshot=snapshot, actor="test", reason="placed cut"
    )
    adjustment = {
        "placementId": "dialogue",
        "sourceId": "camera",
        "sourceSha256": file_fingerprint(source)["sha256"],
        "streamIndex": 0,
        "channels": [0, 1],
        "gainDeltaDb": 1.5,
        "peakCeilingDeltaDb": 1.5,
    }
    workspace.store("tracks").append_revision(
        snapshot={"audioTracks": {"layers": [], "sourceMixAdjustments": [adjustment]}},
        actor="test",
        reason="post-cut voice balance",
    )
    request = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=tmp_path / "mix.mp4",
        frame_rate={"num": 24, "den": 1},
        width=128,
        height=96,
    )
    request["checkpoint"] = "motion-proof"
    return workspace, request, source


def gain(graph):
    return next(op["parameters"] for op in graph["operations"] if op["kind"] == "gain")


def test_compiler_applies_current_tracks_mix_without_changing_cmap_or_request(
    tmp_path, monkeypatch
):
    workspace, request, _ = mix_workspace(tmp_path, monkeypatch)
    before = deepcopy(request)
    cmap_index = deepcopy(workspace.store("cmap").load_index())
    plan = ProofPlanCompiler(workspace).compile(
        request, regression_contract=regression_contract()
    )
    assert gain(plan["audioGraph"])["gainDb"] == 11.5
    assert gain(plan["audioGraph"])["peakCeilingDbfs"] == -3
    assert plan["audioGraph"]["nodes"] == before["audioGraph"]["nodes"]
    assert request == before
    assert workspace.store("cmap").load_index() == cmap_index


def test_cut_proof_keeps_the_approved_cmap_mix(tmp_path, monkeypatch):
    workspace, request, _ = mix_workspace(tmp_path, monkeypatch)
    request["checkpoint"] = "cut-proof"
    plan = ProofPlanCompiler(workspace).compile(
        request, regression_contract=regression_contract()
    )
    assert plan["audioGraph"] == request["audioGraph"]


def test_compiler_rejects_a_second_application_of_source_mix(tmp_path, monkeypatch):
    workspace, request, _ = mix_workspace(tmp_path, monkeypatch)
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.compile(request, regression_contract=regression_contract())
    request["audioGraph"] = plan["audioGraph"]
    with pytest.raises(ProofPlanError) as error:
        compiler.compile(request, regression_contract=regression_contract())
    assert error.value.code == "PROOF_SOURCE_MIX_INVALID"


def test_preflight_binds_mix_controls_even_if_graph_hash_is_recomputed(
    tmp_path, monkeypatch
):
    workspace, request, source = mix_workspace(tmp_path, monkeypatch)
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.compile(request, regression_contract=regression_contract())
    gain(plan["audioGraph"])["gainDb"] -= 1
    plan["proofPlanHash"] = document_hash_excluding(plan, "proofPlanHash")
    result = compiler.preflight(
        plan,
        media_inputs={"camera": source},
        tool_readiness={"proof-plan-executor": True, "ffmpeg": True},
    )
    assert any(
        item["code"] == "PROOF_SOURCE_MIX_INVALID" for item in result["blockers"]
    )


def test_preflight_accepts_the_once_applied_mix(tmp_path, monkeypatch):
    workspace, request, source = mix_workspace(tmp_path, monkeypatch)
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.compile(request, regression_contract=regression_contract())
    result = compiler.preflight(
        plan,
        media_inputs={"camera": source},
        tool_readiness={"proof-plan-executor": True, "ffmpeg": True},
    )
    assert result["status"] == "pass", result["blockers"]


def test_legacy_assembly_cannot_silently_ignore_source_mix(tmp_path, monkeypatch):
    from avo.timeline.materialize import materialize_assembly

    workspace, _, _ = mix_workspace(tmp_path, monkeypatch)
    revision = workspace.store("tracks").revision(
        workspace.require_active("tracks")["headRevisionId"]
    )
    monkeypatch.setattr(
        "avo.timeline.picture_lineage.current_assembly_lock",
        lambda _workspace: ({}, {"tracks": revision}),
    )
    with pytest.raises(ValueError, match="ProofPlan renderer"):
        materialize_assembly(
            workspace=workspace,
            output_path=tmp_path / "never-created.mp4",
            render_contract={},
            delivery_fidelity_policy={},
        )
    assert not (tmp_path / "never-created.mp4").exists()
