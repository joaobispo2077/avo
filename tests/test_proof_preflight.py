from __future__ import annotations

from types import SimpleNamespace

import pytest

from avo.adapters.registry import (
    CapabilityImplementation,
    CapabilityRegistry,
    CapabilityRegistryError,
    default_proof_capability_registry,
)
from avo.timeline.animation import AnimationError, validate_visible_text_policy
from avo.timeline.contracts import file_fingerprint
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.store import ArtifactStore

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


class _Workspace(SimpleNamespace):
    def store(self, artifact_type):
        return self.stores[artifact_type]

    def require_active(self, artifact_type):
        index = self.store(artifact_type).load_index()
        if index["activeState"] != "valid":
            raise RuntimeError(f"{artifact_type} is stale")
        return index


def _plan_fixture(tmp_path, *, output_alias=False):
    timeline = tmp_path / "edit" / "timeline"
    stores = {}
    for name in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        store = ArtifactStore(timeline / f"{name}.json")
        store.initialize(
            artifact_type=name,
            artifact_id=f"video:{name}",
            video_id="video",
            provider="bishop",
            timeline_domain=(
                "raw-source" if name in {"cmap", "sync-map"} else "cmap-output"
            ),
        )
        store.append_revision(snapshot={"name": name}, actor="test", reason="fixture")
        stores[name] = store
    workspace = _Workspace(
        timeline_dir=timeline,
        stores=stores,
        raw_dir=tmp_path,
        video_id="video",
        project={"provider": "bishop"},
    )
    source = tmp_path / "camera.mp4"
    source.write_bytes(b"camera-original")
    request = {
        "iterationId": "iteration-0001",
        "sourceFingerprints": {"camera": file_fingerprint(source)["sha256"]},
        "renderProfile": "proof",
        "output": {
            "path": str(source if output_alias else tmp_path / "proof.mp4"),
            "width": 1280,
            "height": 720,
            "frameRate": {"num": 30, "den": 1},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "videoCodec": "h264",
            "audioCodec": "aac",
        },
        "videoGraph": {
            "operations": [
                {
                    "operationId": "operation-overlay",
                    "kind": "overlay-image",
                    "inputs": ["camera"],
                    "outputRange": {"startFrame": 0, "endFrameExclusive": 30},
                    "parameters": {},
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
            "preflight": ["dependency-lock", "tool-readiness"],
            "microproof": [{"startFrame": 0, "endFrameExclusive": 30}],
            "fullReview": ["watch"],
            "historicalRegression": ["speech", "movement", "events"],
        },
        "visionReviewPlanRef": None,
    }
    contract = {
        "contractId": "contract-iteration-0001",
        "ledgerHash": HASH_A,
        "iterationId": "iteration-0001",
        "obligations": [],
        "historicalRiskWindows": [],
        "conflicts": [],
        "contractHash": HASH_B,
    }
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.compile(request, regression_contract=contract)
    return workspace, compiler, plan, source


def _implementation(identifier, kind, digest):
    return CapabilityImplementation(
        implementation_id=identifier,
        capability="overlay-image",
        kind=kind,
        adapter_id=f"adapter.{identifier}",
        version="1.0.0",
        sha256=digest,
    )


def test_capability_precedence_prefers_builtin_then_provider_then_custom():
    registry = CapabilityRegistry()
    registry.register(_implementation("impl-custom", "custom-project", HASH_C))
    registry.register(_implementation("impl-provider", "provider-component", HASH_B))
    registry.register(_implementation("impl-builtin", "built-in", HASH_A))
    assert registry.resolve("overlay-image").implementation_id == "impl-builtin"
    assert (
        registry.resolve("overlay-image", implementation_id="impl-custom").kind
        == "custom-project"
    )


def test_default_registry_exposes_reusable_timeline_operations():
    registry = default_proof_capability_registry()
    assert registry.resolve("trim").kind == "built-in"
    assert registry.resolve("overlay-video").adapter_id == "ffmpeg.overlay"
    assert registry.resolve("text-card-graphic").adapter_id.startswith("hyperframes")


def test_registry_rejects_command_text_and_identity_rebinding():
    registry = CapabilityRegistry()
    record = {
        "implementationId": "impl-custom",
        "capability": "overlay-image",
        "kind": "custom-project",
        "adapterId": "project.overlay",
        "version": "1.0.0",
        "sha256": HASH_A,
        "command": "python one-off.py",
    }
    with pytest.raises(CapabilityRegistryError, match="command text"):
        registry.register_record(record)
    registry.register(_implementation("impl-builtin", "built-in", HASH_A))
    with pytest.raises(CapabilityRegistryError, match="different content"):
        registry.register(_implementation("impl-builtin", "built-in", HASH_B))


def test_visible_video_text_rejects_em_dash_without_explicit_authorization():
    value = {"graphics": [{"title": "DAY 1 — FIRST LOOK"}]}
    with pytest.raises(AnimationError, match="explicit user authorization"):
        validate_visible_text_policy(value)
    validate_visible_text_policy(
        value, em_dash_authorization_ref="creator-feedback-0042"
    )


def test_preflight_passes_only_exact_locks_media_and_ready_tools(tmp_path):
    _workspace, compiler, plan, source = _plan_fixture(tmp_path)
    report = compiler.preflight(
        plan,
        media_inputs={"camera": source},
        tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
    )
    assert report["status"] == "pass"
    assert report["blockers"] == []


def test_preflight_reports_stale_revision_missing_media_and_bad_fingerprint(tmp_path):
    workspace, compiler, plan, source = _plan_fixture(tmp_path)
    workspace.store("tracks").append_revision(
        snapshot={"changed": True}, actor="test", reason="stale plan"
    )
    missing = compiler.preflight(
        plan,
        media_inputs={},
        tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
    )
    codes = {item["code"] for item in missing["blockers"]}
    assert {"PROOF_REVISION_STALE", "PROOF_MEDIA_MISSING"}.issubset(codes)

    source.write_bytes(b"mutated")
    mismatch = compiler.preflight(
        plan,
        media_inputs={"camera": source},
        tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
    )
    assert "PROOF_DEPENDENCY_LOCK_MISMATCH" in {
        item["code"] for item in mismatch["blockers"]
    }


def test_preflight_blocks_output_alias_capability_and_tool_readiness(tmp_path):
    _workspace, compiler, plan, source = _plan_fixture(tmp_path, output_alias=True)
    plan["capabilityResolution"][0]["status"] = "blocked"
    report = compiler.preflight(
        plan,
        media_inputs={"camera": source},
        tool_readiness={"ffmpeg": False, "proof-plan-executor": True},
    )
    codes = {item["code"] for item in report["blockers"]}
    assert codes.issuperset(
        {
            "PROOF_PLAN_HASH_MISMATCH",
            "PROOF_OUTPUT_ALIASES_INPUT",
            "PROOF_CAPABILITY_GAP",
            "PROOF_TOOL_NOT_READY",
        }
    )


def test_preflight_rejects_forbidden_media_ancestry_recursively(tmp_path):
    _workspace, compiler, plan, source = _plan_fixture(tmp_path)
    report = compiler.preflight(
        plan,
        media_inputs={
            "camera": {
                "path": source,
                "mediaClass": "source",
                "ancestry": [{"mediaClass": "proof"}],
            }
        },
        tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
    )
    assert "PROOF_FORBIDDEN_MEDIA_ANCESTRY" in {
        item["code"] for item in report["blockers"]
    }
