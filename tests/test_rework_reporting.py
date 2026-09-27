from __future__ import annotations

from avo.timeline.review import meaningful_change_summary
from avo.timeline.review_study import build_rework_report


def _item(rework_id, origin, group, *, render=1, review=2, supersedes=None):
    return {
        "reworkId": rework_id,
        "reworkGroupId": group,
        "origin": origin,
        "supersedes": supersedes,
        "impact": {"renderCost": render, "reviewCost": review},
    }


def test_linked_multi_causal_rework_retains_both_causes_without_cost_duplication() -> (
    None
):
    report = build_rework_report(
        {
            "reworkItems": [
                _item("rework-0001", "user-scope-change", "group-0001"),
                _item("rework-0002", "implementation-defect", "group-0001"),
            ]
        }
    )
    assert report["classificationCount"] == 2
    assert report["reworkGroupCount"] == 1
    assert report["categories"]["scopeEvolution"] == {
        "classificationCount": 1,
        "groupCount": 1,
    }
    assert report["categories"]["correctnessRegressions"]["classificationCount"] == 1
    assert report["multiCausalGroups"] == ["group-0001"]
    assert report["costSignals"] == {"renderCost": 1.0, "reviewCost": 2.0}


def test_superseded_classification_is_not_counted_as_current() -> None:
    report = build_rework_report(
        {
            "reworkItems": [
                _item("rework-0001", "agent-reasoning-defect", "group-0001"),
                _item(
                    "rework-0002",
                    "unknown",
                    "group-0001",
                    supersedes="rework-0001",
                ),
            ]
        }
    )
    assert report["classificationCount"] == 1
    assert report["categories"]["correctnessRegressions"]["classificationCount"] == 0
    assert report["categories"]["unknown"]["classificationCount"] == 1


def test_semantic_changes_are_separate_from_mechanical_timeline_shifts() -> None:
    changes = [
        {
            "changeId": "change-0001",
            "kind": "editorial-selection",
            "description": "Add the creator supplied wheel segment.",
        },
        {
            "changeId": "change-0002",
            "kind": "downstream-shift",
            "description": "Move later overlays by 300 frames.",
            "causedBy": "change-0001",
        },
    ]
    summary = meaningful_change_summary(changes)
    assert summary["primarySemanticChanges"] == [changes[0]]
    assert summary["mechanicalDownstreamShifts"] == [changes[1]]
    assert summary["primaryCount"] == summary["mechanicalCount"] == 1
