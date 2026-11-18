"""Canonical compare-and-swap guards do not rebuild or traverse derived work views."""

from avo.timeline.motion_authoring import MotionAuthoringService
from avo.timeline.motion_review import MotionReviewService
from avo.timeline.workspace import TimelineWorkspace
from tests.test_motion_authoring import propose


def test_canonical_head_guard_does_not_reenter_pending_work_projection(
    tmp_path, monkeypatch
):
    import json

    project = tmp_path / "avo.project.json"
    project.write_text(
        json.dumps({"provider": "example", "videoId": "heads", "rawDir": str(tmp_path)})
    )
    workspace = TimelineWorkspace.from_project(project)
    propose(workspace)
    expected = MotionReviewService(workspace).project()["basisHeads"]

    def forbidden(*args, **kwargs):
        raise AssertionError("A canonical head guard rebuilt the derived review")

    monkeypatch.setattr(MotionReviewService, "project", forbidden)
    service = MotionAuthoringService(workspace)
    assert service._heads() == expected
    service._check_heads(expected)
