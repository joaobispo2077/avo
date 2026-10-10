import pytest

from avo.timeline.cmap_service import CMapService
from avo.timeline.lineage import LineageError
from cutting_fixtures import cutting_workspace, source_snapshot


def test_stale_proposal_head_rejected_before_canonical_write(tmp_path):
    workspace, source = cutting_workspace(tmp_path)
    service = CMapService(workspace)
    first = service.author(source_snapshot(source), actor="fixture", reason="initial")
    changed = source_snapshot(source)
    changed["segments"][0]["in"]["ticks"] = 1000
    service.author(changed, actor="fixture", reason="newer selection")
    before = service.store.path.read_bytes()
    with pytest.raises(LineageError, match="stale"):
        service.author(
            source_snapshot(source),
            actor="fixture",
            reason="stale proposal",
            expected_head_hash=first["contentHash"],
        )
    assert service.store.path.read_bytes() == before


def test_current_proposal_head_applies_through_canonical_author(tmp_path):
    workspace, source = cutting_workspace(tmp_path)
    service = CMapService(workspace)
    first = service.author(source_snapshot(source), actor="fixture", reason="initial")
    changed = source_snapshot(source)
    changed["segments"][0]["in"]["ticks"] = 1000
    result = service.author(
        changed,
        actor="fixture",
        reason="verified cut",
        expected_head_hash=first["contentHash"],
    )
    assert result["snapshot"]["segments"][0]["in"]["ticks"] == 1000
    assert result["contentHash"] != first["contentHash"]
