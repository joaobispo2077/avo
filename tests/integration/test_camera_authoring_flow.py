"""Real canonical publication/recovery with a declared unit runtime boundary.

These metadata fixtures do not qualify a video decoder or approve an edit.
Actual encoded source/color/window behavior is tested in camera runtime suites.
"""

import hashlib
import json
from copy import deepcopy

import pytest
from tests.test_camera_commands import declared_camera as camera_capability_fixture
from tests.test_camera_commands import selected_request
from tests.test_motion_authoring import heads, request, select
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_bmap_service import approved_workspace, cue
from tests.test_timeline_tracks_service import canonical_tracks

declared_camera = pytest.fixture(name="declared_camera")(
    camera_capability_fixture.__wrapped__
)
pytestmark = pytest.mark.integration

from avo.timeline.animation import AnimationService
from avo.timeline.bmap_service import BMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.motion_authoring import MotionAuthoringError, MotionAuthoringService
from avo.timeline.tracks import TracksService


def camera_application(tmp_path):
    workspace, _, _ = approved_workspace(tmp_path)
    bmap = BMapService(workspace).author(
        {"cues": [cue()]}, actor="fixture", reason="Existing text"
    )
    tracks = TracksService(workspace).author(
        canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
        actor="fixture",
        reason="Existing source and dialogue",
    )
    animation = AnimationService(workspace).author(
        strategy(), actor="fixture", reason="Existing independent graphic"
    )
    # Read the canonical JSON rather than retaining the fixture's shared region
    # object between the source-picture and dialogue input dictionaries.
    tracks = workspace.store("tracks").revision(tracks["revisionId"])
    service = MotionAuthoringService(workspace, camera_runtime=lambda: "c" * 64)
    proposal_request = selected_request(workspace)
    item = proposal_request["proposal"]["items"][0]
    item["layerIds"] = ["base-video"]
    item["cameraRecipe"].update(
        sourceId="camera",
        sourceSha256=file_fingerprint(workspace.raw_dir / "raw.bin")["sha256"],
    )
    proposed = service.propose(proposal_request)
    chosen = select(workspace, proposed)
    frozen = proposed["proposal"]["items"][0]
    camera_cue = cue()
    camera_cue.update(
        cueId=frozen["cueId"],
        kind="animation",
        targetLayerId="base-video",
        contentRef={
            "componentId": frozen["componentIds"][0],
            "itemId": frozen["itemId"],
        },
    )
    next_tracks = deepcopy(tracks["snapshot"])
    next_tracks["videoTracks"]["layers"][0]["regions"][0]["cueIds"].append(
        frozen["cueId"]
    )
    next_animation = deepcopy(animation["snapshot"])
    next_animation["strategyContractVersion"] = "2.0.0"
    next_animation["components"].append(
        {
            "componentId": frozen["componentIds"][0],
            "lifecycle": {
                "preEntry": "current source framing",
                "entrance": "motivated push",
                "hold": "readable framing",
                "exit": "hold the selected end framing",
            },
            "accessibility": {"reducedMotion": "static framing"},
            "extensions": {"editingCraft": deepcopy(frozen["cameraTreatment"])},
        }
    )
    value = request(
        workspace,
        "camera-apply",
        "apply-selected-camera",
        selection={
            "proposalHash": proposed["proposalRef"]["sha256"],
            "decisionHash": chosen["decisionRef"]["sha256"],
        },
        authoring={
            "bmap": {"cues": [*deepcopy(bmap["snapshot"]["cues"]), camera_cue]},
            "tracks": next_tracks,
            "animation": next_animation,
        },
    )
    return workspace, service, value, animation, tracks


@pytest.mark.parametrize("entrypoint", ["service", "native", "mcp"])
def test_selected_camera_publishes_without_changing_existing_graphic_or_dialogue(
    tmp_path, declared_camera, monkeypatch, entrypoint
):
    workspace, service, value, previous, tracks = camera_application(tmp_path)
    if entrypoint == "service":
        result = service.apply(value)
    else:
        from tests.test_motion_plan_cli import definition

        from avo.adapters.media import camera_provenance
        from avo.mcp.bridge import run_bridged, run_cli

        monkeypatch.setattr(
            camera_provenance,
            "camera_runtime_identity",
            lambda: {"environmentHash": "c" * 64},
        )
        path = tmp_path / "apply-camera.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if entrypoint == "native":
            executed = run_cli(
                [
                    "animation",
                    "camera-apply",
                    "--project",
                    str(workspace.project_path),
                    "--video-id",
                    workspace.video_id,
                    "--request",
                    str(path),
                    "--request-sha256",
                    digest,
                    "--json",
                ]
            )
        else:
            tool = definition("camera-apply")
            assert tool.spec.destructive is True
            executed = run_bridged(
                tool.cli_prefix,
                {
                    "project": str(workspace.project_path),
                    "video_id": workspace.video_id,
                    "request": str(path),
                    "request_sha256": digest,
                },
            )
        assert executed.exit_code == 0, executed.stderr
        result = executed.parsed_json
    assert result["operation"] == "camera-apply"
    assert result["status"] == "committed"
    current = workspace.store("animation").revision(
        result["committedHeads"]["animation"]["revisionId"]
    )["snapshot"]
    assert current["components"][0] == previous["snapshot"]["components"][0]
    assert (
        current["components"][1]["extensions"]["editingCraft"]
        == value["authoring"]["animation"]["components"][1]["extensions"][
            "editingCraft"
        ]
    )
    final_tracks = workspace.store("tracks").revision(
        result["committedHeads"]["tracks"]["revisionId"]
    )["snapshot"]
    assert final_tracks["audioTracks"] == tracks["snapshot"]["audioTracks"]
    assert result["receipt"]["cameraEnvironmentHash"] == "c" * 64
    from avo.timeline.motion_review import MotionReviewService

    projected = MotionReviewService(workspace).project()
    camera_item = next(item for item in projected["items"] if item["itemId"] == "mo04")
    assert camera_item["camera"]["state"] == "authored"
    assert camera_item["componentRef"] == "camera-mo04"
    assert (
        camera_item["camera"]["sourceSha256"]
        == file_fingerprint(workspace.raw_dir / "raw.bin")["sha256"]
    )
    assert workspace.store("animation").load_index()["schemaVersion"] == "2.0.0"
    service.camera_runtime = lambda: pytest.fail("Committed retry re-probed runtime")
    assert service.apply(value)["committedHeads"] == result["committedHeads"]
    altered = deepcopy(result["receipt"])
    altered["cameraEnvironmentHash"] = "e" * 64
    with pytest.raises(MotionAuthoringError, match="environment"):
        service._verify_receipt_intent(value, altered)
    # A crash after commit but before marker cleanup needs no fresh decoder probe.
    from avo.timeline.contracts import content_hash
    from avo.timeline.store import atomic_write_json

    atomic_write_json(
        service._pending,
        {"operationId": value["operationId"], "requestHash": content_hash(value)},
    )
    assert service.apply(value)["committedHeads"] == result["committedHeads"]
    assert not service._pending.exists()


@pytest.mark.parametrize(
    "change",
    [
        "options",
        "omitted",
        "graphic",
        "duplicate-graphic",
        "generic-apply",
        "audio",
        "global",
        "runtime",
    ],
)
def test_camera_apply_rejects_unselected_changes_before_any_publication(
    tmp_path, declared_camera, change
):
    workspace, service, value, _, _ = camera_application(tmp_path)
    before = heads(workspace)
    if change == "options":
        value["authoring"]["animation"]["components"][1]["extensions"]["editingCraft"][
            "camera"
        ]["nodes"][-1]["scale"] = 1.3
    elif change == "omitted":
        value["authoring"]["animation"]["components"].pop()
    elif change == "graphic":
        value["authoring"]["animation"]["components"][0]["lifecycle"]["hold"] = (
            "different graphic"
        )
    elif change == "duplicate-graphic":
        duplicate = deepcopy(value["authoring"]["animation"]["components"][0])
        duplicate["lifecycle"]["hold"] = "unselected hidden change"
        value["authoring"]["animation"]["components"].insert(0, duplicate)
    elif change == "generic-apply":
        value["operation"] = "plan-apply"
    elif change == "audio":
        value["authoring"]["tracks"]["audioTracks"]["layers"][0]["gainDb"] = -5
    elif change == "global":
        value["authoring"]["animation"]["density"] = 5
    else:
        service.camera_runtime = lambda: "d" * 64
    with pytest.raises(MotionAuthoringError):
        service.apply(value)
    assert heads(workspace) == before
    assert not service._pending.exists()


def test_interrupted_camera_publication_recovers_the_same_selected_request(
    tmp_path, declared_camera, monkeypatch
):
    workspace, service, value, _, _ = camera_application(tmp_path)

    def interrupted(*args, **kwargs):
        raise OSError("Synthetic interruption before Animation publication")

    with monkeypatch.context() as patch:
        patch.setattr(AnimationService, "author", interrupted)
        with pytest.raises(MotionAuthoringError, match="interruption"):
            service.apply(value)
    assert service._pending.exists()
    result = service.apply(value)
    assert result["status"] == "committed"
    assert not service._pending.exists()
    assert len(workspace.store("animation").load_index()["revisionRefs"]) == 2
    assert service.apply(value)["committedHeads"] == result["committedHeads"]
