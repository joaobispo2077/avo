"""Explicit source sound anchors survive publication and recheck canonical timing."""

from copy import deepcopy

import pytest
from tests.test_sound_application import application
from tests.test_sound_opportunities import intent

from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.cmap_service import CMapService
from avo.timeline.sound_planning import SoundPlanningError
from avo.timeline.sound_proof import _Selections
from avo.timeline.workspace import WorkspaceError

pytestmark = pytest.mark.integration


def source_intent(cmap):
    source = cmap["sources"][0]
    selected = intent(
        kind="explicit",
        purpose="Accent the explicitly selected original-source moment",
        sourceAnchor={
            "sourceId": source["sourceId"],
            "sourceSha256": source["fingerprint"]["sha256"],
            "segmentId": cmap["segments"][0]["segmentId"],
            "sourceTime": {"ticks": 250, "timebase": {"num": 1, "den": 1000}},
        },
    )
    selected.pop("phase")
    return selected


def source_application(tmp_path):
    workspace, _, service, _, request, _ = application(tmp_path)
    cmap = workspace.store("cmap").load()["revisions"][-1]["snapshot"]
    shown = service.propose(
        {
            "contractVersion": "1.0.0",
            "operation": "propose",
            "operationId": "source-accent",
            "actor": "fixture",
            "reason": "Inspect the selected source point",
            "selection": resolve_editing_craft_selection(
                invocation={"soundMatching": {"enabled": True}}
            ),
            "expectedBasis": request["expectedBasis"],
            "expectedGeneration": request["expectedGeneration"],
            "clock": {
                "frameRate": {"num": 24, "den": 1},
                "sampleRate": 48000,
                "programEndFrame": 24,
            },
            "intents": [source_intent(cmap)],
        }
    )
    request.update(
        operationId="source-accent-apply",
        proposalHash=shown["proposalRef"]["sha256"],
        expectedBasis=shown["proposal"]["basisHeads"],
    )
    return workspace, service, request, shown, cmap


def test_source_point_reaches_canonical_sound_and_rejects_a_later_removed_occurrence(
    tmp_path,
):
    workspace, service, request, shown, cmap = source_application(tmp_path)
    result = service.apply(request)
    tracks = workspace.store("tracks").load()["revisions"][-1]["snapshot"]
    (selected,) = _Selections(workspace, tracks).load()
    assert result["acceptance"] == "pending-listening"
    assert selected["choice"]["fit"]["opportunity"]["programFrame"] == 6
    assert selected["choice"]["fit"]["event"]["resolvedImpactSample"] == 12000
    assert (
        selected["choice"]["fit"]["opportunity"]
        == shown["proposal"]["opportunities"][0]["opportunity"]
    )
    changed = deepcopy(cmap)
    changed["segments"][0]["segmentId"] = "replacement-take"
    CMapService(workspace).author(changed, actor="fixture", reason="Replace occurrence")
    with pytest.raises(WorkspaceError, match="tracks is stale"):
        _Selections(workspace, tracks).load()


@pytest.mark.parametrize("change", ["source", "timing"])
def test_final_sound_validation_rechecks_source_identity_and_mapping(tmp_path, change):
    workspace, service, request, _, cmap = source_application(tmp_path)
    service.apply(request)
    tracks = workspace.store("tracks").load()["revisions"][-1]["snapshot"]
    selected = _Selections(workspace, tracks)
    selected.cmap = deepcopy(cmap)
    if change == "source":
        selected.cmap["sources"][0]["fingerprint"]["sha256"] = "0" * 64
    else:
        selected.cmap["segments"][0]["in"]["ticks"] = 50
    with pytest.raises(SoundPlanningError):
        selected.load()
