from __future__ import annotations

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
