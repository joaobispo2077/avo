from __future__ import annotations

import pytest

from avo.timeline.contracts import content_hash
from avo.timeline.projection import ProjectionError, project_cmap_to_edl
from tests.test_timeline_import_layout import legacy_snapshot, placed_snapshot


def _revision(snapshot, revision_id="r1"):
    return {
        "revisionId": revision_id,
        "contentHash": content_hash(snapshot),
        "snapshot": snapshot,
    }


def _artifact(snapshot):
    return {
        "artifactType": "cmap",
        "artifactId": "main",
        "currentRevisionId": "r1",
        "approvedRevisionId": None,
        "revisions": [_revision(snapshot)],
    }


@pytest.mark.parametrize("segments", [None, "legacy", "malformed", "unmarked-mixed"])
def test_placed_snapshot_cannot_be_lossily_projected_to_legacy_edl(segments):
    snapshot = placed_snapshot()
    if segments in {"legacy", "unmarked-mixed"}:
        snapshot["segments"] = legacy_snapshot()["segments"]
        if segments == "unmarked-mixed":
            snapshot.pop("layoutMode")
    elif segments == "malformed":
        snapshot["segments"] = [{}]
    with pytest.raises(ProjectionError, match="placed"):
        project_cmap_to_edl(_artifact(snapshot))


def test_projection_guards_the_selected_revision_and_preserves_legacy_behavior():
    artifact = _artifact(placed_snapshot())
    artifact["revisions"].append(_revision(legacy_snapshot(), "legacy"))
    result = project_cmap_to_edl(artifact, revision_id="legacy")
    assert result["ranges"] == [{"source": "camera", "start": 0.0, "end": 1.0}]
    assert result["timeline_projection"]["cmapRevisionId"] == "legacy"
    with pytest.raises(ProjectionError, match="placed"):
        project_cmap_to_edl(artifact)
