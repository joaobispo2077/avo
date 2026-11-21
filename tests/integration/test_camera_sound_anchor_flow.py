"""Canonical camera/sound publication and late binding; no decoder or human rating."""

from copy import deepcopy

import pytest
from tests.integration import test_camera_authoring_flow as camera_flow
from tests.test_camera_commands import declared_camera as camera_capability_fixture
from tests.test_sfx_catalog import Facts, annotate, scan
from tests.test_sound_application import SourceProbe
from tests.test_sound_opportunities import intent

from avo.editing_craft import resolve_editing_craft_selection
from avo.sfx_catalog import SfxCatalogService
from avo.timeline.animation import AnimationService
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.sound_planning import SoundPlanningError, SoundPlanningService
from avo.timeline.sound_proof import _Selections

declared_camera = pytest.fixture(name="declared_camera")(
    camera_capability_fixture.__wrapped__
)
pytestmark = pytest.mark.integration


def camera_sound(tmp_path, monkeypatch):
    original = camera_flow.selected_request
    selection = resolve_editing_craft_selection(
        invocation={"camera": {"enabled": True}, "soundMatching": {"enabled": True}}
    )

    def selected(workspace):
        request = original(workspace)
        request["selection"] = deepcopy(selection)
        request["proposal"]["items"][0]["cameraRecipe"]["preset"] = "punch-settle"
        return request

    monkeypatch.setattr(camera_flow, "selected_request", selected)
    workspace, camera, request, _, _ = camera_flow.camera_application(tmp_path)
    camera_cue = request["authoring"]["bmap"]["cues"][-1]
    camera.apply(request)
    snapshot = TimelinePipeline(workspace).motion_plan()
    item = next(
        value
        for value in snapshot["items"]
        if (value.get("camera") or {}).get("state") == "authored"
    )
    library = tmp_path / "sound-library"
    library.mkdir()
    (library / "whoosh.wav").write_bytes(b"camera accent metadata fixture")
    catalogue = SfxCatalogService(workspace, roots={"test": library}, analyzer=Facts())
    generation = scan(catalogue)
    generation = annotate(
        catalogue,
        generation["generationId"],
        generation["entries"][0]["entryId"],
        {
            "rights": {
                "status": "licensed",
                "license": "Fixture",
                "evidenceRef": "fixture-rights",
            },
            "marker": {"sample": 1200, "reviewerRef": "fixture-marker"},
        },
    )
    selected_intent = intent(
        itemId=item["itemId"],
        cueId=camera_cue["cueId"],
        kind="camera-emphasis",
        query="whoosh",
        cameraAnchor={
            "componentId": item["componentRef"],
            "pathHash": item["camera"]["pathHash"],
            "sourceSha256": item["camera"]["sourceSha256"],
            "nodeIndex": 1,
        },
    )
    selected_intent.pop("phase")
    planning = SoundPlanningService(
        workspace, catalogue=catalogue, source_probe=SourceProbe()
    )
    shown = planning.propose(
        {
            "contractVersion": "1.0.0",
            "operation": "propose",
            "operationId": "camera-accent",
            "actor": "creator",
            "reason": "Inspect the selected camera accent",
            "selection": selection,
            "expectedBasis": snapshot["basisHeads"],
            "expectedGeneration": generation["generationId"],
            "clock": {
                "frameRate": {"num": 24, "den": 1},
                "sampleRate": 48000,
                "programEndFrame": 24,
            },
            "intents": [selected_intent],
        }
    )
    event = shown["proposal"]["opportunities"][0]
    assert event["opportunity"] is not None, event["issues"]
    assert event["opportunity"]["programFrame"] == 4
    applied = planning.apply(
        {
            "contractVersion": "1.0.0",
            "operation": "apply",
            "operationId": "camera-accent-apply",
            "actor": "creator",
            "reason": "Choose this synthetic fixture accent",
            "proposalHash": shown["proposalRef"]["sha256"],
            "expectedBasis": shown["proposal"]["basisHeads"],
            "expectedGeneration": generation["generationId"],
            "choices": [
                {
                    "eventId": event["eventId"],
                    "entryId": generation["entries"][0]["entryId"],
                    "trimRange": {"startSample": 0, "endSampleExclusive": 24000},
                    "mix": {
                        "sourceLayout": "stereo",
                        "targetLayout": "stereo",
                        "channelMap": [0, 1],
                        "gainDb": -12,
                        "peakCeilingDbfs": -3,
                        "fadeInSamples": 0,
                        "fadeOutSamples": 0,
                        "ducking": None,
                    },
                }
            ],
            "contexts": [
                {
                    "cueId": event["opportunity"]["cueId"],
                    "role": "main-scene",
                    "orderedEventIds": [],
                    "syntheticEffectApproved": True,
                }
            ],
        }
    )
    return workspace, shown, applied


def test_camera_node_survives_canonical_sound_publication_without_approval_transfer(
    tmp_path, monkeypatch, declared_camera
):
    workspace, shown, applied = camera_sound(tmp_path, monkeypatch)
    assert (
        applied["status"] == "applied" and applied["acceptance"] == "pending-listening"
    )
    tracks = workspace.store("tracks").load()["revisions"][-1]["snapshot"]
    (selection,) = _Selections(workspace, tracks).load()
    assert (
        selection["choice"]["fit"]["opportunity"]
        == shown["proposal"]["opportunities"][0]["opportunity"]
    )
    assert selection["choice"]["fit"]["event"]["resolvedImpactSample"] == 8000
    animation = deepcopy(
        workspace.store("animation").load()["revisions"][-1]["snapshot"]
    )
    component = next(
        value
        for value in animation["components"]
        if "camera" in (value.get("extensions") or {}).get("editingCraft", {})
    )
    component["extensions"]["editingCraft"]["camera"]["nodes"][1]["scale"] += 0.01
    AnimationService(workspace).author(
        animation, actor="creator", reason="Revise the actual camera path"
    )
    with pytest.raises(SoundPlanningError, match="Camera anchor path changed"):
        _Selections(workspace, tracks).load()
