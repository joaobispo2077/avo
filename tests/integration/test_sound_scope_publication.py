"""Optional sound chunk scope shares ordinary admission, receipts and recovery."""

from copy import deepcopy

import pytest
from tests.test_sound_application import application

from avo.timeline.sound_planning import SoundPlanningError, SoundPlanningService


def scoped(request, proposal, selected):
    result = deepcopy(request)
    result["productionScope"] = {
        "clock": {
            key: deepcopy(proposal["clock"][key])
            for key in ("frameRate", "programEndFrame")
        },
        "chunks": [
            {"chunkId": "opening", "startFrame": 0, "endFrameExclusive": 12},
            {"chunkId": "answer", "startFrame": 12, "endFrameExclusive": 24},
        ],
        "selectedChunkIds": selected,
    }
    return result


def test_selected_audio_scope_preserves_picture_and_replays_without_source_work(
    tmp_path,
):
    workspace, catalogue, service, _, request, shown = application(tmp_path)
    request = scoped(request, shown["proposal"], ["opening"])
    original = workspace.store("bmap").load()["revisions"][-1]["snapshot"]["cues"][0]
    result = service.apply(request)
    report = result["receipt"]["productionScope"]
    assert report["request"] == request["productionScope"]
    assert report["contributions"][0]["ownerChunkId"] == "opening"
    assert report["approval"] == "not-granted"
    assert result["acceptance"] == "pending-listening"
    assert result["reviewScope"] == {
        "affectedChunkIds": ["opening", "answer"],
        "outsideProductionChunkIds": ["answer"],
        "approval": "not-granted",
    }
    cues = workspace.store("bmap").load()["revisions"][-1]["snapshot"]["cues"]
    assert next(c for c in cues if c["cueId"] == original["cueId"]) == original

    def forbidden(*args, **kwargs):
        pytest.fail("Completed scoped replay repeated source work")

    replay = SoundPlanningService(
        workspace, catalogue=catalogue, source_probe=forbidden
    ).apply(request)
    assert replay["receiptRef"] == result["receiptRef"]
    assert replay["reviewScope"] == result["reviewScope"]
    assert len(workspace.store("tracks").load_index()["revisionRefs"]) == 1


def test_context_only_sound_scope_is_rejected_before_any_publication(tmp_path):
    workspace, _, service, probe, request, shown = application(tmp_path)
    request = scoped(request, shown["proposal"], ["answer"])
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    with pytest.raises(SoundPlanningError, match="canonical start"):
        service.apply(request)
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before
    assert probe.calls == []


def test_reselecting_identical_audio_does_not_add_listening_sections(tmp_path):
    from tests.test_sound_application import repropose

    workspace, _, service, _, request, shown = application(tmp_path)
    first = service.apply(scoped(request, shown["proposal"], ["opening"]))
    assert first["reviewScope"]["outsideProductionChunkIds"] == ["answer"]
    owners = {
        name: workspace.artifact_path(name).read_bytes()
        for name in ("cmap", "bmap", "tracks", "animation")
    }

    repeated = repropose(service, request, identity="same-sound-choice")
    proposal = service.load(repeated["proposalHash"])["proposal"]
    repeated = scoped(repeated, proposal, ["opening"])
    result = service.apply(repeated)

    assert result["headsCurrent"] is True
    assert result["committedHeads"] == first["committedHeads"]
    assert result["receiptRef"] != first["receiptRef"]
    assert service.apply(repeated)["receiptRef"] == result["receiptRef"]
    assert {
        name: workspace.artifact_path(name).read_bytes() for name in owners
    } == owners
    assert result["reviewScope"]["affectedChunkIds"] == []
    assert result["reviewScope"]["outsideProductionChunkIds"] == []
    assert result["reviewScope"]["approval"] == "not-granted"


def test_resealed_scope_cannot_claim_another_owner_or_drop_its_original_scope(tmp_path):
    from avo.timeline.contracts import content_hash
    from avo.timeline.sound_application import _Application

    _, _, service, _, request, shown = application(tmp_path)
    request = scoped(request, shown["proposal"], ["opening"])
    result = service.apply(request)
    internal = _Application(service)
    for change in ("owner", "missing"):
        receipt = deepcopy(result["receipt"])
        if change == "owner":
            report = receipt["productionScope"]
            report["contributions"][0]["ownerChunkId"] = "answer"
            report["scopeHash"] = content_hash(
                {k: v for k, v in report.items() if k != "scopeHash"}
            )
        else:
            del receipt["productionScope"]
        with pytest.raises(SoundPlanningError, match="exact production ownership"):
            internal._verify_choice_recipe(request, receipt)
    legacy = deepcopy(request)
    del legacy["productionScope"]
    receipt = deepcopy(result["receipt"])
    with pytest.raises(SoundPlanningError, match="exact production ownership"):
        internal._verify_choice_recipe(legacy, receipt)
    del receipt["productionScope"]
    internal._verify_choice_recipe(legacy, receipt)


def test_scoped_sound_cannot_clear_an_unresolved_parent_bmap(tmp_path):
    from tests.test_sound_application import repropose

    workspace, _, service, probe, request, _ = application(tmp_path)
    workspace.store("bmap").set_active_state(
        "stale", reason="Unresolved parent fixture"
    )
    request = repropose(service, request, identity="scoped-stale-parent")
    shown = service.load(request["proposalHash"])
    request = scoped(request, shown["proposal"], ["opening"])
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    with pytest.raises(SoundPlanningError, match="valid BMap"):
        service.apply(request)
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before
    assert probe.calls == []


def test_scoped_sound_recovery_keeps_frozen_ownership_and_has_no_duplicate_event(
    tmp_path, monkeypatch
):
    from avo.timeline.tracks import TracksService

    workspace, catalogue, service, probe, request, shown = application(tmp_path)
    request = scoped(request, shown["proposal"], ["opening"])
    original = TracksService.author

    def interrupted(*args, **kwargs):
        raise OSError("fixture interrupted scoped Tracks write")

    monkeypatch.setattr(TracksService, "author", interrupted)
    with pytest.raises(SoundPlanningError, match="recovery"):
        service.apply(request)
    monkeypatch.setattr(TracksService, "author", original)
    result = SoundPlanningService(
        workspace, catalogue=catalogue, source_probe=probe
    ).apply(request)
    assert result["receipt"]["productionScope"]["request"] == request["productionScope"]
    assert len(workspace.store("bmap").load_index()["revisionRefs"]) == 2
    assert len(workspace.store("tracks").load_index()["revisionRefs"]) == 1
