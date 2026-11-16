"""Runtime identity is observed only for selected executable camera graphs."""

import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.adapters.media import camera_provenance as provenance
from avo.adapters.media import proof_executor
from avo.timeline.contracts import content_hash


def graph():
    return {
        "videoGraph": {
            "operations": [
                {
                    "operationId": "camera-original",
                    "kind": "camera-transform",
                    "parameters": {"sourceSha256": "a" * 64, "optionsHash": "b" * 64},
                }
            ]
        },
        "audioGraph": {"operations": []},
        "events": [],
        "implementationRefs": [{"sha256": "c" * 64}],
        "canonicalInputLock": {"source:original": "a" * 64},
        "output": {"width": 160, "height": 90, "pixelFormat": "gbrp16le"},
        "window": None,
    }


def test_native_implementation_fingerprint_includes_each_camera_code_boundary(
    tmp_path, monkeypatch
):
    from avo import capabilities

    paths = [path.as_posix() for path in capabilities._PROOF_CODE_PATHS]
    for required in (
        "/adapters/media/camera.py",
        "/adapters/media/camera_provenance.py",
        "/adapters/media/proof_precision.py",
        "/timeline/camera.py",
        "/timeline/camera_plan.py",
    ):
        assert any(path.endswith(required) for path in paths)
    kernel = tmp_path / "camera.py"
    kernel.write_bytes(b"original source kernel")
    monkeypatch.setattr(capabilities, "_PROOF_CODE_PATHS", (kernel,))
    before = capabilities._implementation_digest(
        "camera-transform-v1", "ffmpeg.camera-transform"
    )
    kernel.write_bytes(b"changed source kernel")
    assert (
        capabilities._implementation_digest(
            "camera-transform-v1", "ffmpeg.camera-transform"
        )
        != before
    )


def test_frozen_native_identity_uses_the_real_program_without_source_files(
    tmp_path, monkeypatch
):
    from avo import capabilities

    executable = tmp_path / "avo.exe"
    executable.write_bytes(b"frozen code and camera implementation")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(capabilities, "_PROOF_CODE_PATHS", (tmp_path / "absent.py",))
    first = capabilities._implementation_digest(
        "camera-transform-v1", "ffmpeg.camera-transform"
    )
    executable.write_bytes(b"new frozen code and camera implementation")
    assert (
        capabilities._implementation_digest(
            "camera-transform-v1", "ffmpeg.camera-transform"
        )
        != first
    )


@pytest.fixture
def tools(tmp_path, monkeypatch):
    paths = {name: tmp_path / (name + ".exe") for name in ("ffmpeg", "ffprobe")}
    for name, path in paths.items():
        path.write_bytes((name + " installed test runtime").encode())
    monkeypatch.setattr(provenance.shutil, "which", lambda name: str(paths[name]))
    calls = []

    def version(arguments, **kwargs):
        calls.append(arguments)
        name = next(name for name, path in paths.items() if str(path) == arguments[0])
        return SimpleNamespace(
            stdout=f"{name} version 7.1.1 fixture\nconfiguration: pinned\n"
        )

    monkeypatch.setattr(provenance.subprocess, "run", version)
    return paths, calls


def test_unselected_proofs_do_not_inspect_camera_runtime(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unselected proof inspected camera tools")

    monkeypatch.setattr(provenance.shutil, "which", forbidden)
    assert (
        provenance.camera_render_provenance({"videoGraph": {"operations": []}}) is None
    )


def test_recipe_and_runtime_bind_actual_bytes_without_mutating_the_graph(tools):
    execution = graph()
    original = deepcopy(execution)
    observed = provenance.camera_render_provenance(execution)
    assert observed["recipeHash"] == content_hash(
        {
            key: original[key]
            for key in (
                "videoGraph",
                "audioGraph",
                "events",
                "implementationRefs",
                "canonicalInputLock",
                "output",
            )
        }
    )
    assert (
        observed["runtime"]["ffmpeg"]["sha256"]
        != observed["runtime"]["ffprobe"]["sha256"]
    )
    assert len(observed["implementationSha256"]) == 64
    assert execution == original
    for arguments in tools[1]:
        assert arguments[1:] == ["-version"]


@pytest.mark.parametrize("field", ["source", "options", "profile", "window"])
def test_selected_recipe_or_window_changes_the_recorded_identity(tools, field):
    execution = graph()
    before = provenance.camera_render_provenance(execution)
    if field == "window":
        execution["window"] = {"startFrame": 3, "endFrameExclusive": 8}
    elif field == "profile":
        execution["output"]["width"] = 320
    else:
        execution["videoGraph"]["operations"][0]["parameters"][
            "sourceSha256" if field == "source" else "optionsHash"
        ] = "d" * 64
    assert provenance.camera_render_provenance(execution) != before


def test_missing_selected_runtime_fails_before_encoder_or_output(
    tools, tmp_path, monkeypatch
):
    monkeypatch.setattr(provenance.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        proof_executor,
        "_execute_ffmpeg_proof",
        lambda *a, **k: pytest.fail("Encoded without selected runtime"),
    )
    output = tmp_path / "uncreated" / "proof.mkv"
    with pytest.raises(RuntimeError, match="ffmpeg|runtime"):
        proof_executor.execute_ffmpeg_proof(graph(), output)
    assert not output.parent.exists()


def test_execution_reports_runtime_identity_and_rejects_mid_render_replacement(
    tools, tmp_path, monkeypatch
):
    def render(*args, **kwargs):
        return {"producer": {"name": "native", "version": "1"}}

    monkeypatch.setattr(proof_executor, "_execute_ffmpeg_proof", render)
    result = proof_executor.execute_ffmpeg_proof(graph(), tmp_path / "proof.mkv")
    assert (
        result["producer"]["camera"]["runtime"]["ffmpeg"]["version"]
        == "ffmpeg version 7.1.1 fixture"
    )

    def replaced(*args, **kwargs):
        tools[0]["ffmpeg"].write_bytes(b"different runtime")
        return render()

    monkeypatch.setattr(proof_executor, "_execute_ffmpeg_proof", replaced)
    with pytest.raises(RuntimeError, match="runtime|implementation"):
        proof_executor.execute_ffmpeg_proof(graph(), tmp_path / "proof.mkv")


def test_native_port_rejects_a_new_environment_after_preflight(tools, tmp_path):
    from avo.adapters.media.timeline_render import TimelineRenderAdapter
    from avo.timeline.proof_plan import ProofPlanCompiler
    from tests.test_camera_proof_plan import prepared
    from tests.test_proof_plan import regression_contract

    workspace, request, registry, _ = prepared(tmp_path)
    plan = ProofPlanCompiler(workspace, registry).compile(
        request, regression_contract=regression_contract()
    )

    def renderer(execution, output):
        return {"producer": {"camera": provenance.camera_render_provenance(execution)}}

    port = TimelineRenderAdapter(proof_executor=renderer)
    readiness = port.proof_tool_readiness(plan)
    assert readiness["camera-runtime"] is True
    port.render_proof_plan(plan, tmp_path / "unit-contract.mp4", window=None)
    tools[0]["ffmpeg"].write_bytes(b"replaced between preflight and execution")
    with pytest.raises(RuntimeError, match="differs from preflight"):
        port.render_proof_plan(plan, tmp_path / "unit-contract.mp4", window=None)


def test_legacy_readiness_clears_a_previous_camera_environment(tools):
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    port = TimelineRenderAdapter()
    port.proof_tool_readiness(graph())
    assert port.camera_environment is not None
    port.proof_tool_readiness({"videoGraph": {"operations": []}})
    assert port.camera_environment is None


@pytest.mark.parametrize("version", ["4.4.2", "8.0", "N-123456-nightly"])
def test_unqualified_camera_runtime_is_rejected_before_encoding(
    tools, tmp_path, monkeypatch, version
):
    monkeypatch.setattr(
        provenance.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=f"ffmpeg version {version}\n"),
    )
    monkeypatch.setattr(
        proof_executor,
        "_execute_ffmpeg_proof",
        lambda *args, **kwargs: pytest.fail("Encoded an unqualified runtime"),
    )
    destination = tmp_path / "uncreated" / "proof.mkv"
    with pytest.raises(RuntimeError, match="qualified|runtime"):
        proof_executor.execute_ffmpeg_proof(graph(), destination)
    assert not destination.parent.exists()


def test_camera_environment_changes_preflight_and_invalidates_old_microproof_gate(
    tools, tmp_path
):
    from avo.adapters.media.timeline_render import TimelineRenderAdapter
    from avo.timeline.materialize import (
        ProofMaterializationError,
        _require_current_microproof_gate,
    )
    from avo.timeline.proof_plan import ProofPlanCompiler
    from tests.test_camera_proof_plan import prepared
    from tests.test_proof_plan import regression_contract

    workspace, request, registry, _ = prepared(tmp_path)
    compiler = ProofPlanCompiler(workspace, registry)
    plan = compiler.compile(request, regression_contract=regression_contract())
    port = TimelineRenderAdapter()
    first = compiler.preflight(
        plan, media_inputs={}, tool_readiness=port.proof_tool_readiness(plan)
    )
    tools[0]["ffprobe"].write_bytes(b"different probe runtime")
    second = compiler.preflight(
        plan, media_inputs={}, tool_readiness=port.proof_tool_readiness(plan)
    )
    # These compilation fixtures deliberately lack real media. Runtime binding
    # changes independently of those existing source blockers.
    assert first["cameraEnvironmentHash"] != second["cameraEnvironmentHash"]
    assert first["reportHash"] != second["reportHash"]
    gate = {
        "proofPlanId": plan["proofPlanId"],
        "proofPlanHash": plan["proofPlanHash"],
        "preflightHash": first["reportHash"],
    }
    gate["gateHash"] = content_hash(gate)
    with pytest.raises(ProofMaterializationError, match="different plan or preflight"):
        _require_current_microproof_gate(
            plan, gate, preflight_hash=second["reportHash"]
        )
    unbound = compiler.preflight(
        plan,
        media_inputs={},
        tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
    )
    assert any(
        item["code"] == "PROOF_CAMERA_RUNTIME_UNBOUND" for item in unbound["blockers"]
    )


def test_microproof_results_retain_the_actual_camera_producer(
    tools, tmp_path, monkeypatch
):
    from avo.timeline import materialize

    observed = provenance.camera_render_provenance(graph())
    monkeypatch.setattr(
        materialize,
        "_proof_render",
        lambda *args, **kwargs: {
            "status": "pass",
            "output": {"sha256": "d" * 64},
            "graphHash": "e" * 64,
            "producer": {"camera": observed},
        },
    )
    windows = [
        {
            "startFrame": 0,
            "endFrameExclusive": 3,
            "reasons": ["camera"],
            "operationIds": ["camera-original"],
        }
    ]
    result = materialize._render_required_microproofs(
        object(), {"validationPlan": {}}, windows, tmp_path, ".mkv"
    )
    assert result[0]["cameraProvenance"] == observed
