"""Sound may stale existing descendants without mistaking its own writes for a race."""

import pytest

from avo.timeline.animation import AnimationService
from avo.timeline.sound_planning import SoundPlanningError, SoundPlanningService
from avo.timeline.tracks import TracksService
from tests.test_sound_application import application, repropose
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_tracks_service import canonical_tracks


def existing_assembly(tmp_path):
    workspace, catalogue, service, probe, request, _ = application(tmp_path)
    TracksService(workspace).author(
        canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
        actor="fixture",
        reason="Existing dialogue assembly",
    )
    AnimationService(workspace).author(
        strategy(), actor="fixture", reason="Existing motion plan"
    )
    request = repropose(service, request, identity="existing-assembly")
    return workspace, catalogue, service, probe, request


@pytest.mark.parametrize("interrupt", [False, True])
def test_sound_publication_and_fresh_retry_preserve_but_stale_existing_animation(
    tmp_path, monkeypatch, interrupt
):
    workspace, catalogue, service, probe, request = existing_assembly(tmp_path)
    animation = workspace.store("animation")
    original = animation.load_index()
    if interrupt:
        author = TracksService.author

        def unavailable(*args, **kwargs):
            raise OSError("fixture interruption after BMap")

        monkeypatch.setattr(TracksService, "author", unavailable)
        with pytest.raises(SoundPlanningError, match="recovery"):
            service.apply(request)
        assert animation.load_index()["activeState"] == "stale"
        monkeypatch.setattr(TracksService, "author", author)
    result = SoundPlanningService(
        workspace, catalogue=catalogue, source_probe=probe
    ).apply(request)
    assert result["receipt"]["state"] == "committed"
    assert not service.authoring._pending.exists()
    after = animation.load_index()
    assert after["headRevisionId"] == original["headRevisionId"]
    assert after["revisionRefs"] == original["revisionRefs"]
    assert after["approvedRevisionId"] == original["approvedRevisionId"]
    assert after["activeState"] == "stale"
    assert result["acceptance"] == "pending-listening"


def test_preexisting_animation_state_change_is_still_a_conflicting_basis(tmp_path):
    workspace, _, service, _, request = existing_assembly(tmp_path)
    workspace.store("animation").set_active_state("stale", reason="Unrelated change")
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    with pytest.raises(SoundPlanningError, match="basis changed"):
        service.apply(request)
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before
