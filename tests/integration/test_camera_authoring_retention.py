"""Selected native camera requests remain in verified reconstruction closure."""

import pytest
from tests.integration.test_camera_authoring_flow import camera_application
from tests.test_camera_commands import declared_camera as camera_capability_fixture

from avo.timeline.contracts import content_hash
from avo.timeline.motion_retention import retained_motion_paths

declared_camera = pytest.fixture(name="declared_camera")(
    camera_capability_fixture.__wrapped__
)
pytestmark = pytest.mark.integration


def test_camera_reconstruction_retains_actual_propose_and_apply_operations(
    tmp_path, declared_camera
):
    workspace, service, request, _, _ = camera_application(tmp_path)
    result = service.apply(request)
    paths = set(retained_motion_paths(workspace))
    assert workspace.raw_dir / result["proposalRef"]["path"] in paths
    apply_operation = (
        workspace.raw_dir
        / "edit/motion/operations"
        / (content_hash(["camera-apply", request["operationId"]]) + ".json")
    )
    propose_operation = (
        workspace.raw_dir
        / "edit/motion/operations"
        / (
            content_hash(["camera-propose", result["proposal"]["operationId"]])
            + ".json"
        )
    )
    assert propose_operation in paths
    assert apply_operation in paths
