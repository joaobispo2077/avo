from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.adapters.registry import CapabilityImplementation, CapabilityRegistry
from avo.timeline.contracts import (
    content_hash,
    document_hash_excluding,
    file_fingerprint,
)
from avo.timeline.materialize import (
    ProofMaterializationError,
    proof_build_status,
    render_proof_microproofs,
)
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.store import ArtifactStore


class Workspace(SimpleNamespace):
    def store(self, artifact_type):
        return self.stores[artifact_type]

    def require_active(self, artifact_type):
        return self.store(artifact_type).load_index()


def test_representative_json_first_proof_plan_needs_no_orchestration_script(
    tmp_path, monkeypatch
):
    timeline = tmp_path / "edit" / "timeline"
    stores = {}
    for name in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        store = ArtifactStore(timeline / f"{name}.json")
        store.initialize(
            artifact_type=name,
            artifact_id=f"gamevlog:{name}",
            video_id="gamevlog",
            provider="bishop",
            timeline_domain=(
                "raw-source" if name in {"cmap", "sync-map"} else "cmap-output"
            ),
        )
        store.append_revision(
            snapshot={"declaredOperations": ["cut", "overlay", "mix"]},
            actor="test",
            reason="representative canonical timeline",
        )
        stores[name] = store
    workspace = Workspace(
        timeline_dir=timeline,
        pipeline_run_path=timeline / "pipeline-run.json",
        raw_dir=tmp_path,
        video_id="gamevlog",
        project={"provider": "bishop"},
        stores=stores,
    )
    registry = CapabilityRegistry()
    registry.register(
        CapabilityImplementation(
            implementation_id="impl-overlay",
            capability="overlay-image",
            kind="built-in",
            adapter_id="ffmpeg.overlay",
            version="1.0.0",
            sha256="a" * 64,
        )
    )
    contract = {
        "contractId": "contract-iteration-0001",
        "ledgerHash": "b" * 64,
        "iterationId": "iteration-0001",
        "obligations": [],
        "historicalRiskWindows": [],
        "conflicts": [],
        "contractHash": "",
    }
    contract["contractHash"] = document_hash_excluding(contract, "contractHash")
    source = tmp_path / "camera-main.mp4"
    source.write_bytes(b"original-camera-media")
    request = {
        "iterationId": "iteration-0001",
        "sourceFingerprints": {"camera-main": file_fingerprint(source)["sha256"]},
        "renderProfile": "youtube-proof",
        "output": {
            "path": str(tmp_path / "preview" / "gamevlog-proof.mp4"),
            "width": 1920,
            "height": 1080,
            "frameRate": {"num": 30000, "den": 1001},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "videoCodec": "h264_nvenc",
            "audioCodec": "aac",
        },
        "videoGraph": {
            "operations": [
                {
                    "operationId": "overlay-festival",
                    "kind": "overlay-image",
                    "inputs": ["camera-main", "festival-photo"],
                    "outputRange": {"startFrame": 300, "endFrameExclusive": 450},
                    "parameters": {"side": "left"},
                }
            ]
        },
        "audioGraph": {
            "sampleRate": 48000,
            "nodes": [],
            "operations": [],
            "singleFinalEncode": True,
        },
        "events": [],
        "validationPlan": {
            "preflight": ["canonical-lock", "ancestry"],
            "microproof": [{"startFrame": 300, "endFrameExclusive": 450}],
            "fullReview": ["watch"],
            "historicalRegression": ["preserve-approved-content"],
        },
        "visionReviewPlanRef": None,
    }
    plan = ProofPlanCompiler(workspace, registry).compile(
        request, regression_contract=contract
    )
    assert plan["videoGraph"]["operations"][0]["implementationId"] == "impl-overlay"
    assert list(tmp_path.rglob("*.py")) == []
    assert list(tmp_path.rglob("*.ps1")) == []
    assert list(tmp_path.rglob("*.js")) == []

    calls = []

    def execute(execution, output):
        calls.append(execution)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"proof:{execution['window']}".encode())
        return {
            "status": "pass",
            "output": file_fingerprint(output),
            "producer": {"name": "fixture", "version": "1"},
        }

    monkeypatch.setattr("shutil.which", lambda _name: "fixture-tool")
    renderer = TimelineRenderAdapter(proof_executor=execute)
    before = proof_build_status(
        workspace=workspace,
        proof_plan=plan,
        media_inputs={"camera-main": source},
        render_port=renderer,
    )
    assert before["status"] == "ready-for-microproof"
    gate = render_proof_microproofs(
        workspace=workspace,
        proof_plan=plan,
        media_inputs={"camera-main": source},
        render_port=renderer,
    )
    assert gate["status"] == "pass"
    after = proof_build_status(
        workspace=workspace,
        proof_plan=plan,
        media_inputs={"camera-main": source},
        microproof_gate=gate,
        render_port=renderer,
    )
    assert after["status"] == "ready-for-full-build"
    pipeline = TimelinePipeline(workspace)
    snapshots = []

    def record_candidate_snapshot(**values):
        snapshots.append(values)
        return {"snapshotId": "gamevlog-candidate-0001", "state": "rendered"}

    monkeypatch.setattr(
        pipeline, "record_candidate_snapshot", record_candidate_snapshot
    )
    failed_gate = deepcopy(gate)
    failed_gate.pop("path", None)
    failed_gate["results"][0]["status"] = "fail"
    failed_gate["status"] = "fail"
    failed_gate["gateHash"] = content_hash(
        {key: value for key, value in failed_gate.items() if key != "gateHash"}
    )
    with pytest.raises(ProofMaterializationError) as failure:
        pipeline.build_proof_candidate(
            proof_plan=plan,
            microproof_gate=failed_gate,
            media_inputs={"camera-main": source},
            expected_active_snapshot_hash=None,
            render_port=renderer,
        )
    assert failure.value.code == "PROOF_MICROPROOF_FAILED"
    assert snapshots == []

    built = pipeline.build_proof_candidate(
        proof_plan=plan,
        microproof_gate=gate,
        media_inputs={"camera-main": source},
        expected_active_snapshot_hash=None,
        render_port=renderer,
    )
    materialization = built["materialization"]
    assert materialization["proofPlanHash"] == plan["proofPlanHash"]
    assert snapshots[0]["state"] == "rendered"
    assert snapshots[0]["proof_plan"] == plan
    assert calls[-1]["window"] is None
    assert all(item["videoGraph"] == plan["videoGraph"] for item in calls)
    assert all(item["audioGraph"] == plan["audioGraph"] for item in calls)
    assert all(item["events"] == plan["events"] for item in calls)
