from __future__ import annotations

from types import SimpleNamespace

import pytest

from avo.adapters.registry import CapabilityImplementation, CapabilityRegistry
from avo.timeline.contracts import document_hash_excluding
from avo.timeline.proof_plan import ProofPlanCompiler, ProofPlanError
from avo.timeline.store import ArtifactStore

HASH_A = "a" * 64


class Workspace(SimpleNamespace):
    def store(self, artifact_type):
        return self.stores[artifact_type]

    def require_active(self, artifact_type):
        index = self.store(artifact_type).load_index()
        if index["headRevisionId"] is None:
            raise RuntimeError("missing head")
        return index


def workspace_with_heads(tmp_path):
    timeline = tmp_path / "edit" / "timeline"
    stores = {}
    for artifact_type in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        store = ArtifactStore(timeline / f"{artifact_type}.json")
        store.initialize(
            artifact_type=artifact_type,
            artifact_id=f"video:{artifact_type}",
            video_id="video",
            provider="bishop",
            timeline_domain=(
                "raw-source" if artifact_type in {"cmap", "sync-map"} else "cmap-output"
            ),
        )
        store.append_revision(
            snapshot={"artifact": artifact_type},
            actor="test",
            reason="fixture",
        )
        stores[artifact_type] = store
    return Workspace(
        timeline_dir=timeline,
        raw_dir=tmp_path,
        video_id="video",
        project={"provider": "bishop"},
        stores=stores,
    )


def regression_contract(iteration_id="iteration-0001"):
    value = {
        "contractId": f"contract-{iteration_id}",
        "ledgerHash": "b" * 64,
        "iterationId": iteration_id,
        "obligations": [],
        "historicalRiskWindows": [],
        "conflicts": [],
        "contractHash": "",
    }
    value["contractHash"] = document_hash_excluding(value, "contractHash")
    return value


def proof_request(tmp_path):
    return {
        "iterationId": "iteration-0001",
        "sourceFingerprints": {"camera-1": "c" * 64},
        "renderProfile": "proof-720p",
        "output": {
            "path": str(tmp_path / "proof.mp4"),
            "width": 1280,
            "height": 720,
            "frameRate": {"num": 30000, "den": 1001},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "videoCodec": "h264_nvenc",
            "audioCodec": "aac",
        },
        "videoGraph": {
            "operations": [
                {
                    "operationId": "operation-overlay",
                    "kind": "overlay-image",
                    "inputs": ["camera-1"],
                    "outputRange": {"startFrame": 0, "endFrameExclusive": 30},
                    "parameters": {"x": 10},
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
            "preflight": ["lineage"],
            "microproof": [{"startFrame": 0, "endFrameExclusive": 30}],
            "fullReview": ["watch"],
            "historicalRegression": ["complete-speech"],
        },
        "visionReviewPlanRef": None,
    }


def registry():
    result = CapabilityRegistry()
    result.register(
        CapabilityImplementation(
            implementation_id="impl-overlay",
            capability="overlay-image",
            kind="built-in",
            adapter_id="ffmpeg.overlay",
            version="1.0.0",
            sha256=HASH_A,
        )
    )
    return result


def test_proof_plan_locks_canonical_heads_and_is_hash_stable_and_immutable(tmp_path):
    workspace = workspace_with_heads(tmp_path)
    compiler = ProofPlanCompiler(workspace, registry())
    first = compiler.compile(
        proof_request(tmp_path), regression_contract=regression_contract()
    )
    second = compiler.compile(
        proof_request(tmp_path), regression_contract=regression_contract()
    )
    assert first == second
    assert {"cmap", "bmap", "tracks", "animation", "sync-map"}.issubset(
        first["canonicalInputLock"]
    )
    assert first["implementationRefs"][0]["implementationId"] == "impl-overlay"
    assert first["proofPlanHash"] == document_hash_excluding(first, "proofPlanHash")
    assert compiler.path(first["proofPlanId"]).is_file()


def test_proof_plan_blocks_capability_gaps_and_regression_conflicts(tmp_path):
    workspace = workspace_with_heads(tmp_path)
    with pytest.raises(ProofPlanError) as gap:
        ProofPlanCompiler(workspace, CapabilityRegistry()).compile(
            proof_request(tmp_path), regression_contract=regression_contract()
        )
    assert gap.value.code == "PROOF_CAPABILITY_GAP"

    contract = regression_contract()
    contract["conflicts"] = [{"status": "needs-human"}]
    contract["contractHash"] = document_hash_excluding(contract, "contractHash")
    with pytest.raises(ProofPlanError) as conflict:
        ProofPlanCompiler(workspace, registry()).compile(
            proof_request(tmp_path), regression_contract=contract
        )
    assert conflict.value.code == "PROOF_REGRESSION_CONFLICT"
