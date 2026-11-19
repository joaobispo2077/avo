"""Explicit silence can retire owned sound after its visual anchor disappears."""

from copy import deepcopy

import pytest

from avo.timeline.bmap_service import BMapService
from avo.timeline.sound_planning import SoundPlanningError, SoundPlanningService
from tests.test_sound_application import application, repropose
from tests.test_timeline_bmap_service import cue


@pytest.mark.parametrize("state", ["visual-only", "all-cues", "reused-audio-cue"])
def test_retired_event_silence_removes_only_the_exact_owned_contribution(
    tmp_path, state
):
    workspace, catalogue, service, probe, request, _ = application(tmp_path)
    service.apply(request)
    cmap = workspace.store("cmap").head_hash()
    bmap = workspace.store("bmap")
    snapshot = deepcopy(bmap.load()["revisions"][-1]["snapshot"])
    visual_id = request["contexts"][0]["cueId"]
    sound_cue = next(c for c in snapshot["cues"] if c["kind"] == "sfx")
    snapshot["cues"] = [c for c in snapshot["cues"] if c["cueId"] != visual_id]
    if state == "all-cues":
        snapshot["cues"] = []
    elif state == "reused-audio-cue":
        sound_cue.update(
            kind="text",
            contentRef={"text": "Different canonical owner"},
            targetLayerId="graphics",
        )
    unrelated = cue()
    unrelated["cueId"] = "unrelated-visual"
    unrelated["contentRef"] = {"text": "Keep this unchanged"}
    snapshot["cues"].append(unrelated)
    BMapService(workspace).author(
        snapshot, actor="fixture", reason="Retired visual anchor"
    )
    retired = repropose(service, request, identity="retired-event")
    retired["choices"][0].update(entryId=None, trimRange=None, mix=None)
    retired["contexts"] = []
    count = len(probe.calls)
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    if state == "reused-audio-cue":
        with pytest.raises(SoundPlanningError):
            service.apply(retired)
        assert {
            p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
        } == before
        return
    result = service.apply(retired)
    assert result["receipt"]["state"] == "committed"
    assert len(probe.calls) == count
    assert workspace.store("cmap").head_hash() == cmap
    assert bmap.load()["revisions"][-1]["snapshot"]["cues"] == [unrelated]
    assert (
        workspace.store("tracks").load()["revisions"][-1]["snapshot"]["audioTracks"][
            "layers"
        ]
        == []
    )
    heads = result["committedHeads"]
    replay = SoundPlanningService(workspace, catalogue=catalogue).apply(retired)
    assert replay["committedHeads"] == heads
