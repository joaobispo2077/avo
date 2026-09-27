from __future__ import annotations

from types import SimpleNamespace

import pytest

from avo.timeline.iterations import IterationLedgerError, IterationLedgerService

SHA = "a" * 64


def _service(tmp_path):
    timeline = tmp_path / "edit" / "timeline"
    timeline.mkdir(parents=True)
    workspace = SimpleNamespace(
        timeline_dir=timeline,
        video_id="video-1",
        project={"provider": "bishop"},
    )
    return IterationLedgerService(workspace)


def _request(rework_items):
    return {
        "intent": {"requestedChanges": ["update"]},
        "canonicalBasis": {"cmap": SHA},
        "proofPlanRef": {"artifactId": "proof-plan-0001", "sha256": SHA},
        "reworkItems": rework_items,
    }


def _evidence():
    return [{"evidenceId": "feedback-0001", "sha256": SHA}]


def _item(origin=None, **overrides):
    value = {
        "summary": "The creator supplied another clip after approval.",
        "impact": {"affectedArtifacts": ["cmap"], "programWindows": []},
        "evidenceRefs": _evidence() if origin and origin != "unknown" else [],
        "confidence": 0.9 if origin and origin != "unknown" else 0.0,
        "capabilityGap": None,
        "supersedes": None,
    }
    if origin is not None:
        value["origin"] = origin
    value.update(overrides)
    return value


def test_missing_attribution_defaults_to_unknown_without_blame(tmp_path) -> None:
    result = _service(tmp_path).record_iteration(
        _request([_item()]), actor="agent", reason="record uncertain rework"
    )
    classification = result["ledger"]["reworkItems"][0]
    assert classification["origin"] == "unknown"
    assert classification["confidence"] == 0.0


@pytest.mark.parametrize(
    "origin",
    [
        "user-scope-change",
        "creator-preference-refinement",
        "agent-reasoning-defect",
        "implementation-defect",
        "source-limitation",
        "external-dependency-failure",
    ],
)
def test_supported_origins_require_evidence_and_retain_impact(tmp_path, origin) -> None:
    service = _service(tmp_path)
    result = service.record_iteration(
        _request([_item(origin)]), actor="agent", reason="classify rework"
    )
    assert result["ledger"]["reworkItems"][0]["origin"] == origin
    with pytest.raises(IterationLedgerError, match="requires evidence"):
        _service(tmp_path / "empty").record_iteration(
            _request([_item(origin, evidenceRefs=[])]),
            actor="agent",
            reason="unsupported inference",
        )


def test_capability_gap_requires_reusable_operation_description(tmp_path) -> None:
    service = _service(tmp_path)
    with pytest.raises(IterationLedgerError, match="capability details"):
        service.record_iteration(
            _request([_item("avo-capability-gap")]),
            actor="agent",
            reason="missing details",
        )
    result = service.record_iteration(
        _request(
            [
                _item(
                    "avo-capability-gap",
                    capabilityGap={
                        "operation": "mirrored-vertical-fill",
                        "desiredBehavior": "Reusable vertical-video presentation",
                    },
                )
            ]
        ),
        actor="agent",
        reason="record capability gap",
    )
    assert result["ledger"]["reworkItems"][0]["capabilityGap"]["operation"]


def test_supersession_preserves_original_and_blocks_competing_replacement(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    first = service.record_iteration(
        _request([_item("implementation-defect")]),
        actor="agent",
        reason="initial classification",
    )
    original = first["ledger"]["reworkItems"][0]
    second = service.record_iteration(
        _request([_item("unknown", supersedes=original["reworkId"])]),
        actor="agent",
        reason="evidence changed",
    )
    assert second["ledger"]["reworkItems"][0] == original
    assert second["ledger"]["reworkItems"][1]["supersedes"] == original["reworkId"]
    with pytest.raises(IterationLedgerError, match="already superseded"):
        service.record_iteration(
            _request([_item("unknown", supersedes=original["reworkId"])]),
            actor="agent",
            reason="competing replacement",
        )
