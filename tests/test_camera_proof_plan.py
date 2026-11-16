"""Versioned proof compilation uses frozen canonical camera intent, never a no-op."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from avo.capabilities import CapabilityImplementation, default_proof_capability_registry
from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.contracts import (
    ContractError,
    load_schema,
    validate_document,
    validate_proof_plan_document,
)
from avo.timeline.proof_plan import ProofPlanCompiler, ProofPlanError
from tests.test_camera_contract_compatibility import advanced
from tests.test_camera_planning import component, contribution, cue
from tests.test_proof_plan import (
    proof_request,
    registry,
    regression_contract,
    workspace_with_heads,
)


def prepared(tmp_path):
    workspace = workspace_with_heads(tmp_path)
    value = advanced()
    camera = component()
    camera["lifecycle"] = value["components"][0]["lifecycle"]
    camera["accessibility"] = value["components"][0]["accessibility"]
    frozen = resolve_editing_craft_selection(invocation={"camera": {"enabled": True}})
    camera["extensions"]["editingCraft"]["options"] = frozen
    value["components"] = [camera]
    workspace.store("bmap").append_revision(
        snapshot={"cues": [cue("camera-push", 0, 30)]},
        actor="fixture",
        reason="One canonical clock",
    )
    workspace.store("tracks").append_revision(
        snapshot={
            "videoTracks": {
                "layers": [
                    {
                        "layerId": "presenter",
                        "source": {"sha256": "a" * 64},
                        "regions": [{"cueIds": ["cue-camera-push"]}],
                    }
                ]
            }
        },
        actor="fixture",
        reason="Selected source layer",
    )
    value["dependencies"] = {
        name: workspace.store(name).revision(
            workspace.store(name).load_index()["headRevisionId"]
        )["contentHash"]
        for name in ("cmap", "bmap", "tracks")
    }
    workspace.store("animation").append_revision(
        snapshot=value,
        actor="fixture",
        reason="Typed compilation fixture, no media approval",
    )
    request = proof_request(tmp_path)
    request["sourceFingerprints"] = {"camera-main": "a" * 64}
    request["output"].update(frameRate={"num": 30, "den": 1}, pixelFormat="yuv420p")
    request["videoGraph"] = {"operations": [contribution()]}
    selected = registry()
    selected.register(default_proof_capability_registry().resolve("trim"))
    # This declared unit implementation proves compilation only, not FFmpeg readiness.
    selected.register(
        CapabilityImplementation(
            implementation_id="impl-camera-transform",
            capability="camera-transform-v1",
            kind="built-in",
            adapter_id="ffmpeg.camera-transform",
            version="1.0.0",
            sha256="e" * 64,
        )
    )
    return workspace, request, selected, frozen


def test_camera_compilation_emits_v2_and_the_real_v1_schema_rejects_it(tmp_path):
    workspace, request, selected, frozen = prepared(tmp_path)
    original = deepcopy(request)
    plan = ProofPlanCompiler(workspace, selected).compile(
        request, regression_contract=regression_contract()
    )
    assert plan["schemaVersion"] == "2.0.0"
    assert plan["requiredReaderCapabilities"] == ["camera-transform-v1"]
    camera = next(
        operation
        for operation in plan["videoGraph"]["operations"]
        if operation["kind"] == "camera-transform"
    )
    assert camera["implementationId"] == "impl-camera-transform"
    assert camera["parameters"]["optionsHash"] == frozen["selectionHash"]
    assert not Draft202012Validator(load_schema("avo.proof-plan.schema.json")).is_valid(
        plan
    )
    validate_document(plan, "avo.proof-plan.v2.schema.json")
    assert (
        ProofPlanCompiler(workspace, selected).load(plan["proofPlanId"])[
            "proofPlanHash"
        ]
        == plan["proofPlanHash"]
    )
    assert request == original


def test_missing_camera_runtime_is_reported_without_silently_changing_the_edit(
    tmp_path,
):
    workspace, request, _, _ = prepared(tmp_path)
    with pytest.raises(ProofPlanError) as failure:
        ProofPlanCompiler(workspace, registry()).compile(
            request, regression_contract=regression_contract()
        )
    assert failure.value.code == "PROOF_CAMERA_UNAVAILABLE"


def test_source_lock_changes_and_injected_camera_operations_cannot_override_canonical_intent(
    tmp_path,
):
    workspace, request, selected, _ = prepared(tmp_path)
    changed = deepcopy(request)
    changed["sourceFingerprints"]["camera-main"] = "b" * 64
    with pytest.raises(ProofPlanError, match="source|fingerprint"):
        ProofPlanCompiler(workspace, selected).compile(
            changed, regression_contract=regression_contract()
        )
    request["videoGraph"]["operations"].append(
        {"kind": "camera-transform", "operationId": "injected"}
    )
    with pytest.raises(ProofPlanError, match="canonical|camera"):
        ProofPlanCompiler(workspace, selected).compile(
            request, regression_contract=regression_contract()
        )


def test_camera_v2_contract_rejects_executable_expressions(tmp_path):
    workspace, request, selected, _ = prepared(tmp_path)
    plan = ProofPlanCompiler(workspace, selected).compile(
        request, regression_contract=regression_contract()
    )
    camera = next(
        operation
        for operation in plan["videoGraph"]["operations"]
        if operation["kind"] == "camera-transform"
    )
    camera["parameters"]["expression"] = "untrusted filter"
    with pytest.raises(ContractError):
        validate_document(plan, "avo.proof-plan.v2.schema.json")


def test_native_adapter_preserves_the_camera_reader_contract(tmp_path):
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    workspace, request, selected, _ = prepared(tmp_path)
    plan = ProofPlanCompiler(workspace, selected).compile(
        request, regression_contract=regression_contract()
    )
    captured = []

    def executor(execution, output):
        captured.append(execution)
        return {"status": "pass"}

    TimelineRenderAdapter(proof_executor=executor).render_proof_plan(
        plan, tmp_path / "unit-port-only.mp4", window=None
    )
    assert captured[0]["schemaVersion"] == "2.0.0"
    assert captured[0]["requiredReaderCapabilities"] == ["camera-transform-v1"]


@pytest.mark.parametrize(
    "document",
    [
        None,
        [],
        {"schemaVersion": []},
        {"schemaVersion": {}},
        {"schemaVersion": "3.0.0"},
        {"schemaVersion": "1.0.0", "videoGraph": None},
        {"schemaVersion": "1.0.0", "videoGraph": {"operations": [None]}},
    ],
)
def test_proof_dispatch_rejects_malformed_documents_as_contract_errors(document):
    with pytest.raises(ContractError):
        validate_proof_plan_document(document)
