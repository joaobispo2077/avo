"""Connected service regression; generated media and fixture-only review/assembly evidence."""

from __future__ import annotations

import shutil

import pytest
from test_ffmpeg_proof_executor import _recording
from test_master_delivery_review import Review, transcript_generator

from avo import project_inventory
from avo.timeline.approval_service import require_native_cut_materialization
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.delivery import DeliveryService
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import canonical_proof_media_inputs
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.reconstruction import (
    build_reconstruction_bundle,
    verify_reconstruction_bundle,
)
from avo.timeline.store import atomic_write_json
from avo.timeline.workspace import TimelineWorkspace
from avo.wrap import build_wrap_payload

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="actual ffmpeg/ffprobe required",
)


def _proof(tmp_path):
    source = tmp_path / "camera.mkv"
    _recording(source)
    project = tmp_path / "avo.project.json"
    atomic_write_json(
        project,
        {
            "schemaVersion": "1.0.0",
            "provider": "fixture-provider",
            "videoId": "pipeline-repair",
            "rawDir": str(tmp_path),
        },
    )
    workspace = TimelineWorkspace.from_project(project)
    workspace.initialize()
    snapshot = {
        "sources": [
            {
                "sourceId": "camera",
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
        ],
        "segments": [
            {
                "segmentId": f"segment-{index}",
                "sourceId": "camera",
                "in": {"ticks": index * 500, "timebase": {"num": 1, "den": 1000}},
                "out": {
                    "ticks": (index + 1) * 500,
                    "timebase": {"num": 1, "den": 1000},
                },
            }
            for index in range(2)
        ],
    }
    workspace.store("cmap").append_revision(
        snapshot=snapshot, actor="fixture", reason="generated media"
    )
    sync = workspace.store("sync-map")
    revision = sync.append_revision(
        snapshot={"sources": snapshot["sources"]},
        actor="fixture",
        reason="fixture sync",
    )
    sync.record_decision(
        decision="approved",
        revision_id=revision["revisionId"],
        revision_hash=revision["contentHash"],
        candidate_hash=revision["contentHash"],
        dependency_hashes={"sync-map": revision["contentHash"]},
        actor="fixture-reviewer",
        checkpoint="sync-map",
        scope="exact-sync",
        reason="synthetic fixture only, no human footage approval",
        evidence_bundle_hash=content_hash({"fixture": "sync"}),
    )
    request = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-fixture",
        output=tmp_path / "edit" / "preview" / "cut.mp4",
        frame_rate={"num": 25, "den": 1},
    )
    contract = {
        "contractId": "contract-fixture",
        "ledgerHash": "a" * 64,
        "iterationId": "iteration-fixture",
        "obligations": [],
        "historicalRiskWindows": [],
        "conflicts": [],
        "contractHash": "b" * 64,
    }
    plan = ProofPlanCompiler(workspace).compile(request, regression_contract=contract)
    pipeline = TimelinePipeline(workspace)
    inputs = canonical_proof_media_inputs(workspace, plan)
    gate = pipeline.render_proof_microproofs(proof_plan=plan, media_inputs=inputs)
    result = pipeline.build_proof_candidate(
        proof_plan=plan,
        media_inputs=inputs,
        microproof_gate=gate,
        expected_active_snapshot_hash=None,
    )
    return workspace, pipeline, plan, result


@pytest.mark.parametrize("partial_cleanup", [False, True])
def test_native_candidate_review_delivery_and_cleanup_are_exact_boundaries(
    tmp_path, partial_cleanup
):
    workspace, pipeline, plan, result = _proof(tmp_path)
    candidate = tmp_path / "edit" / "preview" / "cut.mp4"
    record = result["materialization"]
    record = {key: value for key, value in record.items() if key != "path"}
    dependencies = require_native_cut_materialization(workspace, record, str(candidate))
    assert dependencies["proof-plan"] == plan["proofPlanHash"]
    assert all(
        workspace.store(name).load_index()["headRevisionId"] is None
        for name in ("bmap", "tracks", "animation")
    )
    # These are explicit test stand-ins at the external transcript/review boundary.
    sidecars = transcript_generator(candidate, tmp_path / "edit")
    transcript = {
        "fingerprint": file_fingerprint(sidecars["json"]),
        "sourceSha256": file_fingerprint(candidate)["sha256"],
    }
    reviewing = pipeline.record_candidate_snapshot(
        state="reviewing",
        candidate=candidate,
        iteration_id=plan["iterationId"],
        proof_plan=plan,
        materialization=record,
        transcript=transcript,
        expected_active_snapshot_hash=pipeline.active_candidate_snapshot()[
            "snapshotHash"
        ],
    )
    digest = file_fingerprint(candidate)["sha256"]
    fixture_review = {
        "artifactId": "fixture-review",
        "sha256": content_hash({"fixture": "review", "candidate": digest}),
        "candidateSha256": digest,
        "proofPlanSha256": plan["proofPlanHash"],
    }
    fixture_regression = {
        "artifactId": "fixture-regression",
        "sha256": content_hash({"fixture": "regression", "candidate": digest}),
        "candidateSha256": digest,
    }
    fixture_approval = {
        "artifactId": "fixture-approval",
        "sha256": content_hash({"fixture": "approval", "candidate": digest}),
        "candidateSha256": digest,
    }
    approved = pipeline.record_candidate_snapshot(
        state="approved",
        candidate=candidate,
        iteration_id=plan["iterationId"],
        proof_plan=plan,
        materialization=record,
        transcript=transcript,
        review=fixture_review,
        regression_result=fixture_regression,
        approval=fixture_approval,
        expected_active_snapshot_hash=reviewing["snapshotHash"],
    )
    # An assembly receipt is a service-boundary fixture, not a claim that cut-proof
    # materialization itself is deliverable. Full assembly rendering has separate tests.
    assembly_body = {
        "kind": "assembly",
        "materializationId": "assembly-fixture",
        "output": file_fingerprint(candidate),
        "producer": {"name": "fixture-only"},
        "canonicalInputLock": plan["canonicalInputLock"],
    }
    assembly = {**assembly_body, "materializationHash": content_hash(assembly_body)}
    assembly_path = tmp_path / "edit" / "delivery" / "assembly-fixture.json"
    atomic_write_json(assembly_path, assembly)
    delivery = DeliveryService(workspace)
    basename = "pipeline-repair-master-v001"
    master = tmp_path / "edit" / "masters" / f"{basename}.mp4"
    delivery.prepare(
        candidate=candidate,
        master=master,
        dependencies=dependencies,
        materialization=assembly,
        materialization_path=assembly_path,
        review_runner=Review(),
        transcript_generator=transcript_generator,
    )
    assert (
        delivery.approve(actor="fixture-reviewer", reason="synthetic fixture only")[
            "state"
        ]
        == "delivered"
    )
    build_reconstruction_bundle(workspace, master_basename=basename, actor="fixture")
    scratch = tmp_path / "edit" / "cache.bin"
    scratch.write_bytes(b"disposable")
    runner = (lambda path: None) if partial_cleanup else None
    options = {"rimraf_runner": runner} if runner else {}
    outcome = project_inventory.run_cleanup(tmp_path, basename, **options)
    assert master.exists() and workspace.raw_dir.joinpath("camera.mkv").exists()
    verify_reconstruction_bundle(tmp_path)
    assert (
        pipeline.active_candidate_snapshot()["snapshotHash"] == approved["snapshotHash"]
    )
    assert assembly_path.exists()
    inventory = project_inventory.build_inventory_report(tmp_path, basename)
    wrap_args = {
        "session_id": "fixture",
        "provider": "fixture-provider",
        "master_basename": basename,
        "summary": "fixture",
        "status": "final",
    }
    if partial_cleanup:
        assert outcome.leftover > 0 and scratch.exists()
        with pytest.raises(ValueError, match="incomplete"):
            build_wrap_payload(inventory, **wrap_args)
    else:
        final = build_wrap_payload(inventory, **wrap_args)
        assert not scratch.exists()
        assert final["space"]["freedBytes"] == outcome.freed_bytes > 0
        assert (
            sum(row["bytes"] for row in final["files"]["deletedOnCleanup"])
            == outcome.freed_bytes
        )
