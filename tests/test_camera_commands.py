"""Focused camera operations reuse immutable motion choices and canonical owners."""

import pytest

from avo import capabilities
from avo.timeline.motion_authoring import MotionAuthoringError, MotionAuthoringService
from tests.test_camera_concept_authoring import camera_request
from tests.test_motion_authoring import workspace as authoring_workspace

workspace = pytest.fixture(name="workspace")(authoring_workspace.__wrapped__)


def test_native_camera_registration_is_shipped_without_inspecting_tools(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Static capability registration inspected camera tools")

    monkeypatch.setattr("avo.adapters.media.camera_provenance.shutil.which", forbidden)
    implementation = capabilities.default_proof_capability_registry().resolve(
        "camera-transform-v1", implementation_id="impl-camera-transform"
    )
    assert implementation is not None
    assert implementation.kind == "built-in"
    assert implementation.adapter_id == "ffmpeg.camera-transform"


@pytest.fixture
def declared_camera(monkeypatch):
    registry = capabilities.default_proof_capability_registry()
    if registry.resolve("camera-transform-v1") is None:
        registry.register(
            capabilities.CapabilityImplementation(
                implementation_id="impl-camera-transform",
                capability="camera-transform-v1",
                kind="built-in",
                adapter_id="ffmpeg.camera-transform",
                version="1.0.0",
                sha256="d" * 64,
            )
        )
    monkeypatch.setattr(
        capabilities, "default_proof_capability_registry", lambda: registry
    )
    return registry


def selected_request(workspace, **kwargs):
    value = camera_request(workspace, **kwargs)
    value["operation"] = "camera-propose"
    return value


def test_camera_proposal_freezes_observed_environment_and_replays_without_probe(
    workspace, declared_camera
):
    calls = []

    def runtime():
        calls.append("explicit-camera-runtime")
        return "c" * 64

    service = MotionAuthoringService(workspace, camera_runtime=runtime)
    value = selected_request(workspace)
    first = service.propose(value)
    assert first["operation"] == "camera-propose"
    assert first["proposal"]["cameraEnvironmentHash"] == "c" * 64
    assert first["proposal"]["operation"] == "camera-propose"
    again = service.propose(value)
    assert again["proposalRef"] == first["proposalRef"]
    assert calls == ["explicit-camera-runtime"]
    assert not workspace.artifact_path("animation").exists()


@pytest.mark.parametrize(
    "problem", ["disabled", "static", "unavailable", "invalid-runtime"]
)
def test_camera_proposal_rejects_unselected_or_unready_work_before_freezing(
    workspace, declared_camera, problem
):
    from avo.editing_craft import resolve_editing_craft_selection

    value = selected_request(workspace)
    calls = []

    def runtime():
        calls.append(True)
        if problem == "unavailable":
            raise RuntimeError("Selected camera runtime unavailable")
        return "invalid" if problem == "invalid-runtime" else "c" * 64

    if problem == "disabled":
        value["selection"] = resolve_editing_craft_selection()
    elif problem == "static":
        value["proposal"]["items"][0].pop("cameraRecipe")
    with pytest.raises(MotionAuthoringError):
        MotionAuthoringService(workspace, camera_runtime=runtime).propose(value)
    assert not workspace.pipeline_run_path.exists()
    assert not (workspace.raw_dir / "edit/motion/proposals").exists()
    if problem in {"disabled", "static"}:
        assert calls == []


def test_camera_proposal_requires_registered_native_capability_without_probe(
    workspace, monkeypatch
):
    monkeypatch.setattr(
        capabilities,
        "default_proof_capability_registry",
        capabilities.CapabilityRegistry,
    )

    def forbidden():
        pytest.fail("Probed unavailable camera implementation")

    with pytest.raises(MotionAuthoringError, match="capability|implementation"):
        MotionAuthoringService(workspace, camera_runtime=forbidden).propose(
            selected_request(workspace)
        )
    assert not workspace.pipeline_run_path.exists()


def test_generic_motion_proposals_do_not_inspect_camera_runtime(workspace):
    from avo.editing_craft import resolve_editing_craft_selection
    from tests.test_motion_authoring import item, request

    def forbidden():
        pytest.fail("Default motion proposal inspected camera runtime")

    value = request(
        workspace,
        "plan-propose",
        "ordinary-static-plan",
        selection=resolve_editing_craft_selection(),
        proposal={"items": [item()]},
    )
    result = MotionAuthoringService(workspace, camera_runtime=forbidden).propose(value)
    assert result["operation"] == "plan-propose"
    assert "cameraEnvironmentHash" not in result["proposal"]


@pytest.mark.parametrize("entrypoint", ["native", "mcp"])
def test_camera_propose_is_available_through_native_and_mcp_entrypoints(
    workspace, declared_camera, monkeypatch, entrypoint
):
    import json

    from avo.adapters.media import camera_provenance
    from avo.mcp.bridge import run_bridged, run_cli
    from tests.test_motion_plan_cli import definition

    calls = []

    def runtime():
        calls.append("selected-camera")
        return {"environmentHash": "c" * 64}

    monkeypatch.setattr(
        camera_provenance, "camera_runtime_identity", runtime, raising=False
    )
    path = workspace.raw_dir / "camera-request.json"
    path.write_text(json.dumps(selected_request(workspace)), encoding="utf-8")
    if entrypoint == "native":
        result = run_cli(
            [
                "animation",
                "camera-propose",
                "--project",
                str(workspace.project_path),
                "--request",
                str(path),
                "--json",
            ]
        )
    else:
        tool = definition("camera-propose")
        assert tool.cli_prefix == ("animation", "camera-propose")
        result = run_bridged(
            tool.cli_prefix,
            {"project": str(workspace.project_path), "request": str(path)},
        )
    assert result.exit_code == 0, result.stderr
    assert result.parsed_json["operation"] == "camera-propose"
    assert result.parsed_json["proposal"]["cameraEnvironmentHash"] == "c" * 64
    assert calls == ["selected-camera"]
