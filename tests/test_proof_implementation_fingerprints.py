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
