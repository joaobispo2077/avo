from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import (
    ProofMaterializationError,
    canonical_proof_media_inputs,
)
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.store import ArtifactStore, atomic_write_json


class Workspace(SimpleNamespace):
    def store(self, name):
        return self.stores[name]

    def require_active(self, name):
        index = self.store(name).load_index()
        if index["headRevisionId"] is None or index["activeState"] != "valid":
            raise RuntimeError(f"{name} has no valid active revision")
        return index


def setup_cut(tmp_path):
    source = tmp_path / "camera.mkv"
    source.write_bytes(b"fingerprinted raw source")
    stores = {}
    for name in ProofPlanCompiler.CANONICAL_ARTIFACTS:
        store = ArtifactStore(tmp_path / "edit" / "timeline" / f"{name}.json")
        store.initialize(
            artifact_type=name,
            artifact_id=f"video:{name}",
            video_id="video",
            provider="bishop",
            timeline_domain="raw-source"
            if name in {"cmap", "sync-map"}
            else "cmap-output",
        )
        if name in {"cmap", "sync-map"}:
            store.append_revision(
                snapshot={
                    "sources": [
                        {"sourceId": "camera", "fingerprint": file_fingerprint(source)}
                    ]
                },
                actor="test",
                reason="raw cut basis",
            )
        stores[name] = store
    workspace = Workspace(
        stores=stores,
        raw_dir=tmp_path,
        timeline_dir=tmp_path / "edit" / "timeline",
        project={"provider": "bishop"},
    )
    request = {
        "checkpoint": "cut-proof",
        "iterationId": "iteration-0001",
        "sourceFingerprints": {"camera": file_fingerprint(source)["sha256"]},
        "renderProfile": "cut-360p",
        "output": {
            "path": str(tmp_path / "edit" / "preview" / "proof.mp4"),
            "width": 640,
            "height": 360,
            "frameRate": {"num": 25, "den": 1},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "videoCodec": "libx264",
            "audioCodec": "aac",
        },
        "videoGraph": {"operations": []},
        "audioGraph": {
            "sampleRate": 48000,
            "nodes": [],
            "operations": [],
            "singleFinalEncode": True,
        },
        "events": [],
        "validationPlan": {
            "preflight": ["lineage"],
            "microproof": [{"startFrame": 0, "endFrameExclusive": 25}],
            "fullReview": ["watch"],
            "historicalRegression": [],
        },
    }
    contract = {
        "contractId": "contract-initial-cut",
        "ledgerHash": "a" * 64,
        "iterationId": "iteration-0001",
        "obligations": [],
        "historicalRiskWindows": [],
        "conflicts": [],
        "contractHash": "b" * 64,
    }
    return workspace, request, contract, source


def test_initial_cut_locks_absent_maps_and_resolves_raw_without_tracks(tmp_path):
    workspace, request, contract, source = setup_cut(tmp_path)
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.compile(request, regression_contract=contract)
    for name in compiler.CUT_OPTIONAL_ARTIFACTS:
        assert plan["canonicalInputLock"][f"absent:{name}"] == content_hash(
            workspace.store(name).load_index()
        )
        assert workspace.store(name).load_index()["headRevisionId"] is None
    inputs = canonical_proof_media_inputs(workspace, plan)
    assert inputs["camera"]["path"] == source
    assert (
        compiler.preflight(
            plan, media_inputs=inputs, tool_readiness={"proof-plan-executor": True}
        )["status"]
        == "pass"
    )


@pytest.mark.parametrize("name", ["bmap", "tracks", "animation"])
@pytest.mark.parametrize("change", ["revision", "header"])
def test_initial_cut_absence_stales_on_new_revision_or_index_change(
    tmp_path, name, change
):
    workspace, request, contract, source = setup_cut(tmp_path)
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.compile(request, regression_contract=contract)
    store = workspace.store(name)
    if change == "revision":
        store.append_revision(
            snapshot={"changed": True}, actor="test", reason="new phase"
        )
    else:
        index = store.load_index()
        index["updatedAt"] = "2026-10-05T12:00:00Z"
        atomic_write_json(store.path, index)
    report = compiler.preflight(
        plan,
        media_inputs={"camera": source},
        tool_readiness={"proof-plan-executor": True},
    )
    assert any(
        item["code"] == "PROOF_REVISION_STALE" and item["entityRef"] == name
        for item in report["blockers"]
    )
    if name == "tracks":
        with pytest.raises(ProofMaterializationError, match="Tracks absence"):
            canonical_proof_media_inputs(workspace, plan)


@pytest.mark.parametrize("checkpoint", [None, "motion-proof", "pre-master", "deliver"])
def test_later_and_unspecified_checkpoints_still_require_all_maps(tmp_path, checkpoint):
    workspace, request, contract, _source = setup_cut(tmp_path)
    request = deepcopy(request)
    if checkpoint is None:
        request.pop("checkpoint")
    else:
        request["checkpoint"] = checkpoint
    with pytest.raises(RuntimeError, match="bmap has no valid active revision"):
        ProofPlanCompiler(workspace).compile(request, regression_contract=contract)


def test_cut_proof_cannot_lock_stale_empty_index(tmp_path):
    workspace, request, contract, _source = setup_cut(tmp_path)
    store = workspace.store("bmap")
    index = store.load_index()
    index["activeState"] = "stale"
    atomic_write_json(store.path, index)
    with pytest.raises(RuntimeError, match="bmap has no valid active revision"):
        ProofPlanCompiler(workspace).compile(request, regression_contract=contract)


def builder_workspace(tmp_path):
    workspace, _, _, source = setup_cut(tmp_path)
    sources = []
    segments = []
    for ordinal in (1, 2):
        source_id = f"camera-{ordinal}"
        sources.append(
            {
                "sourceId": source_id,
                "fingerprint": file_fingerprint(source),
                "streamMetadata": {
                    "videoStreamIndex": 0,
                    "audioSelection": {
                        "streamIndex": 2,
                        "sourceSampleRate": 48000,
                        "sourceLayout": "stereo",
                        "channels": [0],
                        "outputLayout": "dual-mono",
                    },
                },
            }
        )
        segments.append(
            {
                "segmentId": f"segment-{ordinal}",
                "sourceId": source_id,
                "in": {"ticks": 0, "timebase": {"num": 1, "den": 1000}},
                "out": {"ticks": 1000, "timebase": {"num": 1, "den": 1000}},
            }
        )
    return workspace, {"sources": sources, "segments": segments}


def build_request(workspace, snapshot):
    workspace.store("cmap").append_revision(
        snapshot=snapshot, actor="test", reason="explicit source metadata"
    )
    return initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=workspace.raw_dir / "edit" / "preview" / "cut.mp4",
        frame_rate={"num": 60, "den": 1},
    )


@pytest.mark.parametrize("budget", [1, 200])
def test_video_tail_policy_is_explicit_source_scoped_and_deepcopied(tmp_path, budget):
    workspace, snapshot = builder_workspace(tmp_path)
    policy = {"mode": "hold-last-frame", "maxHoldMilliseconds": budget}
    snapshot["sources"][0]["streamMetadata"]["videoTailPolicy"] = policy
    request = build_request(workspace, snapshot)
    trims = request["videoGraph"]["operations"]
    assert trims[0]["parameters"]["videoTailPolicy"] == policy
    assert "videoTailPolicy" not in trims[1]["parameters"]
    trims[0]["parameters"]["videoTailPolicy"]["maxHoldMilliseconds"] = 201
    assert policy["maxHoldMilliseconds"] == budget
    assert all(
        "videoTailPolicy" not in op["parameters"]
        for op in request["audioGraph"]["operations"]
    )


def test_no_automatic_video_tail_policy_for_untagged_sources(tmp_path):
    workspace, snapshot = builder_workspace(tmp_path)
    request = build_request(workspace, snapshot)
    assert all(
        "videoTailPolicy" not in op["parameters"]
        for op in request["videoGraph"]["operations"]
    )


@pytest.mark.parametrize(
    "policy",
    [
        None,
        [],
        {},
        {"mode": "pad-black", "maxHoldMilliseconds": 200},
        {"mode": "hold-last-frame"},
        {"mode": "hold-last-frame", "maxHoldMilliseconds": 200, "extra": True},
        *(
            {"mode": "hold-last-frame", "maxHoldMilliseconds": value}
            for value in (0, -1, 201, True, 1.5, "200")
        ),
    ],
)
def test_invalid_canonical_video_tail_policy_fails_closed(tmp_path, policy):
    workspace, snapshot = builder_workspace(tmp_path)
    snapshot["sources"][0]["streamMetadata"]["videoTailPolicy"] = policy
    with pytest.raises(ValueError, match="video tail policy"):
        build_request(workspace, snapshot)
