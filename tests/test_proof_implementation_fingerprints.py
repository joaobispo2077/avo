import pytest

from avo import capabilities
from avo.timeline.proof_plan import ProofPlanCompiler
from test_initial_cut_proof_plan import setup_cut


@pytest.mark.parametrize("changed_file", [0, 1])
def test_native_executor_or_adapter_change_invalidates_compiled_plan(
    tmp_path, monkeypatch, changed_file
):
    executor = tmp_path / "proof_executor.py"
    adapter = tmp_path / "timeline_render.py"
    executor.write_bytes(b"executor version one")
    adapter.write_bytes(b"adapter version one")
    paths = (executor, adapter)
    monkeypatch.setattr(capabilities, "_PROOF_CODE_PATHS", paths)
    workspace, request, contract, source = setup_cut(tmp_path)
    request["videoGraph"]["operations"] = [
        {
            "operationId": "trim-source-0001",
            "kind": "trim",
            "inputs": ["camera"],
            "outputRange": {"startFrame": 0, "endFrameExclusive": 25},
            "parameters": {},
        }
    ]
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.compile(request, regression_contract=contract)
    readiness = {"proof-plan-executor": True, "ffmpeg": True}
    assert (
        compiler.preflight(
            plan, media_inputs={"camera": source}, tool_readiness=readiness
        )["status"]
        == "pass"
    )
    original = plan["implementationRefs"][0]["sha256"]
    paths[changed_file].write_bytes(b"modified executable implementation")
    current = capabilities.default_proof_capability_registry().resolve("trim")
    assert current.sha256 != original
    report = compiler.preflight(
        plan, media_inputs={"camera": source}, tool_readiness=readiness
    )
    assert any(
        item["code"] == "PROOF_IMPLEMENTATION_STALE"
        and item["entityRef"] == "impl-trim"
        for item in report["blockers"]
    )


def test_native_implementation_digest_is_independent_of_install_location(
    tmp_path, monkeypatch
):
    digests = []
    for directory in (tmp_path / "first", tmp_path / "second"):
        directory.mkdir()
        executor = directory / "proof_executor.py"
        adapter = directory / "timeline_render.py"
        executor.write_bytes(b"same executor")
        adapter.write_bytes(b"same adapter")
        monkeypatch.setattr(capabilities, "_PROOF_CODE_PATHS", (executor, adapter))
        digests.append(
            capabilities.default_proof_capability_registry().resolve("trim").sha256
        )
    assert digests[0] == digests[1]


def test_generated_clip_is_native_and_does_not_require_hyperframes():
    registry = capabilities.default_proof_capability_registry()
    generated = registry.resolve("generated-clip")
    assert generated.implementation_id == "impl-generated-clip"
    assert generated.adapter_id == "ffmpeg.generated-clip"
    assert registry.resolve("overlay-video").adapter_id == "ffmpeg.overlay"


def test_generated_preflight_rejects_changed_receipt_before_execution(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from avo.timeline.generated_assets import GeneratedAssetService
    from tests.integration.test_code_drawn_proof_executor import (
        _add_generated,
        _generated,
    )

    workspace, request, contract, source = setup_cut(tmp_path)
    service = GeneratedAssetService(
        SimpleNamespace(timeline_dir=tmp_path / "edit/timeline")
    )
    asset = _generated(tmp_path, service, asset_id="generated-proof-test", opaque=False)
    execution = {
        "videoGraph": {"operations": []},
        "canonicalInputLock": {},
        "implementationRefs": [],
    }
    _add_generated(execution, asset, kind="overlay-video", start=1, end=10)
    request["videoGraph"] = execution["videoGraph"]
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.compile(request, regression_contract=contract)
    key = "generated:" + asset["record"]["assetId"]
    assert plan["canonicalInputLock"][key] == asset["record"]["recordHash"]
    assert "input-lock:generated-proof-test" in plan["canonicalInputLock"]
    report = compiler.preflight(
        plan,
        media_inputs={"camera": source},
        tool_readiness={"proof-plan-executor": True, "ffmpeg": True},
    )
    assert any(
        item["code"] == "PROOF_GENERATED_ASSET_STALE" for item in report["blockers"]
    )
    asset["lock_path"].write_text("changed lock", encoding="utf-8")
    report = compiler.preflight(
        plan,
        media_inputs={"camera": source},
        tool_readiness={"proof-plan-executor": True, "ffmpeg": True, key: True},
    )
    assert any(
        item["code"] == "PROOF_GENERATED_ASSET_STALE" for item in report["blockers"]
    )


@pytest.mark.parametrize("capability", ["text-card-graphic", "caption-ordering"])
def test_recorded_code_drawn_strategy_cannot_resolve_hyperframes_implicitly(
    tmp_path, capability
):
    from avo.timeline.proof_plan import ProofPlanError
    from tests.code_drawn_asset_fixture import canonical_asset
    from tests.test_proof_plan import proof_request, regression_contract

    asset = canonical_asset(tmp_path)
    request = proof_request(asset.workspace.raw_dir)
    from avo.timeline.contracts import file_fingerprint

    request["sourceFingerprints"] = {
        "camera": file_fingerprint(asset.workspace.raw_dir / "raw.bin")["sha256"]
    }
    operation = request["videoGraph"]["operations"][0]
    operation["kind"] = capability
    operation.pop("implementationId", None)
    with pytest.raises(ProofPlanError, match="recorded|code-drawn|incompatible"):
        ProofPlanCompiler(asset.workspace).compile(
            request, regression_contract=regression_contract()
        )
