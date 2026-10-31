"""The microproof gate is published only after fresh batch dependency checks."""

import os
from types import SimpleNamespace

import pytest

from avo.timeline import materialize
from avo.timeline.contracts import ContractError, file_fingerprint


@pytest.mark.parametrize("change_source", [False, True])
def test_batch_source_guard_precedes_gate_publication(
    tmp_path, monkeypatch, change_source
):
    source = tmp_path / "raw.bin"
    source.write_bytes(b"original")
    stamp = source.stat()
    plan = {
        "proofPlanId": "proof-plan-batch",
        "proofPlanHash": "a" * 64,
        "output": {"path": str(tmp_path / "full.mp4")},
        "videoGraph": {"operations": []},
        "validationPlan": {
            "microproof": [
                {"startFrame": 0, "endFrameExclusive": 30},
                {"startFrame": 60, "endFrameExclusive": 90},
            ]
        },
    }

    class Compiler:
        def require_preflight(self, *args, **kwargs):
            file_fingerprint(source)
            return {"reportHash": "b" * 64}

    def render(port, value, output, *, window):
        file_fingerprint(source)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"internal check")
        if change_source and window["startFrame"] == 60:
            source.write_bytes(b"replaced")
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        return {
            "status": "pass",
            "output": file_fingerprint(output),
            "graphHash": "c" * 64,
        }

    monkeypatch.setattr(materialize, "_proof_plan_value", lambda *a: (Compiler(), plan))
    monkeypatch.setattr(materialize, "_configured_proof_port", lambda *a: object())
    monkeypatch.setattr(materialize, "_proof_readiness", lambda *a: {})
    monkeypatch.setattr(materialize, "_proof_render", render)
    workspace = SimpleNamespace(timeline_dir=tmp_path / "timeline")
    request = {"workspace": workspace, "proof_plan": plan, "media_inputs": {}}
    if change_source:
        with pytest.raises(ContractError, match="changed"):
            materialize.render_proof_microproofs(**request)
        assert not list(workspace.timeline_dir.rglob("gate-*.json"))
    else:
        result = materialize.render_proof_microproofs(**request)
        assert result["status"] == "pass"
        assert len(result["results"]) == 2
        assert len(list(workspace.timeline_dir.rglob("gate-*.json"))) == 1
