from avo.timeline.command_handlers import CommandHandlers


class Pipeline:
    def __init__(self):
        self.workspace = object()
        self.calls = []

    def candidate_status(self):
        return {"snapshotId": "candidate-0001", "state": "rendered"}

    def proof_build_status(self, **payload):
        self.calls.append(("status", payload))
        return {
            "status": "ready-for-full-build",
            "proofPlanHash": "a" * 64,
            "preflight": {"status": "pass", "blockers": []},
            "microproofGate": {"state": "pass", "gateHash": "b" * 64},
            "candidate": self.candidate_status(),
        }

    def render_proof_microproofs(self, **payload):
        self.calls.append(("microproof", payload))
        return {"status": "pass", "gateHash": "b" * 64}

    def build_proof_candidate(self, **payload):
        self.calls.append(("build", payload))
        return {"candidateSnapshot": self.candidate_status()}


def test_pipeline_handler_exposes_preflight_microproof_and_candidate_status():
    pipeline = Pipeline()
    result = CommandHandlers(pipeline).execute(
        "pipeline",
        "proof-status",
        {
            "proofPlan": {"proofPlanId": "proof-plan-0001"},
            "mediaInputs": {"camera": "camera.mp4"},
            "microproofGate": {"gateHash": "b" * 64},
        },
    )
    assert result["mutated"] is False
    assert result["result"]["status"] == "ready-for-full-build"
    assert result["result"]["candidate"]["state"] == "rendered"


def test_pipeline_handler_routes_microproof_and_full_build_through_gate_methods():
    pipeline = Pipeline()
    handlers = CommandHandlers(pipeline)
    microproof = handlers.execute(
        "pipeline",
        "proof-microproof",
        {
            "mutation": "microproof-gate",
            "proofPlan": {"proofPlanId": "proof-plan-0001"},
            "mediaInputs": {"camera": "camera.mp4"},
        },
    )
    assert microproof["result"]["status"] == "pass"
    build = handlers.execute(
        "pipeline",
        "proof-build",
        {
            "mutation": "candidate-snapshot",
            "proofPlan": {"proofPlanId": "proof-plan-0001"},
            "microproofGate": {"gateHash": "b" * 64},
            "mediaInputs": {"camera": "camera.mp4"},
            "expectedActiveSnapshotHash": None,
        },
    )
    assert build["result"]["candidateSnapshot"]["state"] == "rendered"
    assert [item[0] for item in pipeline.calls] == ["microproof", "build"]
