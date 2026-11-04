"""All canonical originals must remain current until proof evidence is published."""

from types import SimpleNamespace

import pytest

from avo.timeline import contracts, materialize
from tests.test_proof_validation_stage import replace_preserving_metadata


def test_muted_source_changed_during_full_render_cannot_publish_materialization(
    tmp_path, monkeypatch
):
    muted = tmp_path / "muted-original.wav"
    muted.write_bytes(b"original")
    output = tmp_path / "candidate.mkv"
    plan = {
        "proofPlanId": "proof-plan-test",
        "proofPlanHash": "a" * 64,
        "canonicalInputLock": {
            "source:muted": contracts.file_fingerprint(muted)["sha256"]
        },
        "output": {"path": str(output)},
        "renderProfile": "test",
    }

    def preflight(*args, **kwargs):
        contracts.file_fingerprint(muted)
        return {"reportHash": "b" * 64}

    def render(*args, **kwargs):
        replace_preserving_metadata(muted)
        output.write_bytes(b"candidate")
        return {"output": contracts.file_fingerprint(output)}

    workspace = SimpleNamespace(timeline_dir=tmp_path / "timeline")
    compiler = SimpleNamespace(require_preflight=preflight)
    monkeypatch.setattr(
        materialize, "_proof_plan_value", lambda *args: (compiler, plan)
    )
    monkeypatch.setattr(materialize, "_configured_proof_port", lambda *args: object())
    monkeypatch.setattr(materialize, "_proof_readiness", lambda *args: {})
    monkeypatch.setattr(
        materialize, "_load_microproof_gate", lambda *args: {"gateHash": "c" * 64}
    )
    monkeypatch.setattr(
        materialize, "_require_current_microproof_gate", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(materialize, "_proof_render", render)
    with pytest.raises(contracts.ContractError, match="changed"):
        materialize.materialize_proof_plan(
            workspace=workspace,
            proof_plan=plan,
            microproof_gate={},
            media_inputs={"muted": {"path": muted}},
            render_port=object(),
        )
    assert not (workspace.timeline_dir / "materializations").exists()
