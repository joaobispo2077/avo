"""Orchestration policy only; fake output bytes are not physical media evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from avo.timeline import materialize
from avo.timeline.contracts import file_fingerprint
from avo.timeline.proof_plan import ProofPlanCompiler
from tests.test_initial_cut_proof_plan import setup_cut


class PlanAwarePort:
    def __init__(self, calls, configured=False):
        self.calls, self.configured = calls, configured

    def for_proof_plan(self, workspace, plan):
        self.calls.append((workspace, plan["proofPlanHash"]))
        return PlanAwarePort(self.calls, configured=True)

    def proof_tool_readiness(self, plan):
        return {"proof-plan-executor": self.configured}

    def render_proof_plan(self, plan, output, *, window):
        assert self.configured
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"unit-only metadata output")
        return {
            "status": "pass",
            "output": file_fingerprint(output),
            "graphHash": "c" * 64,
            "producer": {"name": "unit", "version": "1"},
        }


def _fixture(tmp_path):
    workspace, request, contract, source = setup_cut(tmp_path)
    plan = ProofPlanCompiler(workspace).compile(request, regression_contract=contract)
    return workspace, plan, {"camera": source}


@pytest.mark.parametrize("explicit", [False, True])
def test_status_configures_the_selected_plan_before_tool_readiness(
    tmp_path, monkeypatch, explicit
):
    workspace, plan, media = _fixture(tmp_path)
    calls = []
    port = PlanAwarePort(calls)
    monkeypatch.setattr(materialize, "create_timeline_render_port", lambda: port)
    result = materialize.proof_build_status(
        workspace=workspace,
        proof_plan=plan,
        media_inputs=media,
        render_port=port if explicit else None,
    )
    assert result["status"] == "ready-for-microproof"
    assert calls == [(workspace, plan["proofPlanHash"])]


def test_full_build_uses_the_same_selected_plan_configuration_as_microproof(
    tmp_path, monkeypatch
):
    workspace, plan, media = _fixture(tmp_path)
    calls = []
    port = PlanAwarePort(calls)
    monkeypatch.setattr(materialize, "create_timeline_render_port", lambda: port)
    gate = materialize.render_proof_microproofs(
        workspace=workspace, proof_plan=plan, media_inputs=media
    )
    assert gate["status"] == "pass"
    result = materialize.materialize_proof_plan(
        workspace=workspace, proof_plan=plan, microproof_gate=gate, media_inputs=media
    )
    assert result["kind"] == "proof-plan"
    assert len(calls) == 2
