from __future__ import annotations

from pathlib import Path

from avo.timeline import ports


def test_all_effect_boundaries_are_protocols() -> None:
    names = {
        "MediaIdentityPort",
        "RawInventoryPort",
        "TranscriptionPort",
        "WatchReviewPort",
        "TimelineRenderPort",
        "DeterministicQcPort",
        "AudioQcPort",
        "VisualQcPort",
        "AccessibilityQcPort",
        "RightsPolicyPort",
        "SyncValidationPort",
        "FixExecutorPort",
        "ApprovalPort",
        "ClockPort",
        "ArtifactStorePort",
        "WaveformAnalysisPort",
        "CustomComponentPort",
        "ExactStillPort",
        "ProofExecutionPort",
        "VisionCapabilityPort",
        "MultimodalPassPort",
    }
    assert names <= set(vars(ports))
    assert all(getattr(getattr(ports, name), "_is_protocol", False) for name in names)


def test_structured_tool_error_has_stable_shape() -> None:
    error = ports.ToolError(
        code="WATCH_UNAVAILABLE",
        message="missing",
        retryable=True,
        remediation="install Watch",
    )
    assert error.to_dict() == {
        "code": "WATCH_UNAVAILABLE",
        "message": "missing",
        "retryable": True,
        "remediation": "install Watch",
    }


def test_new_execution_ports_are_structural_and_narrow() -> None:
    class Waveform:
        def analyze(self, source: Path, **request):
            return {"source": str(source), **request}

    class Component:
        def execute(self, component, output_dir: Path, **request):
            return {"component": component, "output": str(output_dir), **request}

    class Still:
        def extract(self, source: Path, output: Path, **request):
            return {"source": str(source), "output": str(output), **request}

    class Proof:
        def execute(self, proof_plan, output: Path, **request):
            return {"plan": proof_plan, "output": str(output), **request}

    class Capability:
        def probe(self, **request):
            return dict(request)

    class Pass:
        def review_pass(self, candidate: Path, **request):
            return {"candidate": str(candidate), **request}

    assert isinstance(Waveform(), ports.WaveformAnalysisPort)
    assert isinstance(Component(), ports.CustomComponentPort)
    assert isinstance(Still(), ports.ExactStillPort)
    assert isinstance(Proof(), ports.ProofExecutionPort)
    assert isinstance(Capability(), ports.VisionCapabilityPort)
    assert isinstance(Pass(), ports.MultimodalPassPort)
