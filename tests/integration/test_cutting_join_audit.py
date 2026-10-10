"""Original-source join accounting; generated tones do not certify speech."""

from copy import deepcopy

import pytest

from avo.timeline.cmap_service import CMapService
from avo.timeline.cutting_audit import audit_joins
from avo.timeline.lineage import LineageError
from cutting_fixtures import cutting_workspace, source_snapshot

pytestmark = pytest.mark.integration


def test_canonical_join_audit_preserves_rejected_gap_and_original_source(tmp_path):
    workspace, source = cutting_workspace(tmp_path, enabled=True)
    snapshot = source_snapshot(source)
    first = snapshot["segments"][0]
    first["out"]["ticks"] = 12000
    second = deepcopy(first)
    second["segmentId"] = "unit-two"
    second["in"]["ticks"] = 24000
    second["out"]["ticks"] = 48000
    snapshot["segments"].append(second)
    service = CMapService(workspace)
    revision = service.author(snapshot, actor="fixture", reason="retain disjoint units")
    original = deepcopy(revision["snapshot"])
    joins = audit_joins(original, {"num": 60, "den": 1})
    assert len(joins) == 1
    assert joins[0]["leftSourceRange"]["endTicksExclusive"] == 12000
    assert joins[0]["rightSourceRange"]["startTicks"] == 24000
    assert "source-discontinuity" in joins[0]["flags"]
    assert joins[0]["deletionAuthorized"] is False
    assert service.store.revision(revision["revisionId"])["snapshot"] == original
    assert original["sources"][0]["locator"] == str(source)


def test_audit_does_not_admit_a_preview_as_canonical_raw_input(tmp_path):
    workspace, source = cutting_workspace(tmp_path, enabled=True)
    snapshot = source_snapshot(source)
    snapshot["sources"][0]["locator"] = str(workspace.raw_dir / "edit" / "preview.wav")
    with pytest.raises(LineageError, match="derived edit/proof"):
        CMapService(workspace).author(
            snapshot, actor="fixture", reason="invalid ancestor"
        )
