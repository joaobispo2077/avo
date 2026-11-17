"""Only actual selected/history/recovery sound evidence survives reconstruction."""

import pytest

from avo.timeline.motion_retention import MotionRetentionError, retained_motion_paths
from tests.test_sound_application import application


def test_selected_sound_retains_exact_request_receipts_and_proposal(tmp_path):
    workspace, _, service, _, request, shown = application(tmp_path)
    applied = service.apply(request)
    unrelated = service.root / "proposals" / ("b" * 64 + ".json")
    unrelated.write_text("{}", encoding="utf-8")
    paths = set(retained_motion_paths(workspace))
    assert workspace.raw_dir / shown["proposalRef"]["path"] in paths
    assert workspace.raw_dir / applied["receiptRef"]["path"] in paths
    assert workspace.raw_dir / applied["receipt"]["requestRef"]["path"] in paths
    assert unrelated not in paths
    assert not any(path.suffix == ".wav" for path in paths)
    (workspace.raw_dir / shown["proposalRef"]["path"]).write_text(
        "{}", encoding="utf-8"
    )
    with pytest.raises(MotionRetentionError):
        retained_motion_paths(workspace)


def test_pending_sound_application_retains_recovery_without_a_tracks_head(
    tmp_path, monkeypatch
):
    from avo.timeline.tracks import TracksService

    workspace, _, service, _, request, shown = application(tmp_path)
    monkeypatch.setattr(
        TracksService,
        "author",
        lambda *a, **k: (_ for _ in ()).throw(OSError("interrupted")),
    )
    with pytest.raises(ValueError, match="recovery") as failure:
        service.apply(request)
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    paths = set(retained_motion_paths(workspace))
    assert service.authoring._pending in paths
    assert workspace.raw_dir / failure.value.receipt_ref["path"] in paths
    assert workspace.raw_dir / shown["proposalRef"]["path"] in paths
    assert {p: p.read_bytes() for p in before} == before
