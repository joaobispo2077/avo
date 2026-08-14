from __future__ import annotations

from pathlib import Path

from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService

from tests.test_timeline_bmap_service import approved_workspace, cue
from tests.test_timeline_cmap_service import snapshot


def test_cmap_change_persists_all_downstream_stale_before_render(tmp_path: Path) -> None:
    workspace, _, _ = approved_workspace(tmp_path)
    bmap = BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="beat")
    for artifact_type in ("tracks", "animation"):
        workspace.store(artifact_type).append_revision(
            snapshot={"basis": bmap["contentHash"], "items": []},
            actor="avo",
            reason="downstream fixture",
            dependencies=[
                {
                    "artifactType": "bmap",
                    "artifactId": workspace.store("bmap").load_index()["artifactId"],
                    "revisionId": bmap["revisionId"],
                    "contentSha256": bmap["contentHash"],
                }
            ],
        )
    raw = workspace.raw_dir / "raw.bin"
    CMapService(workspace).author(
        snapshot(raw, start=50, end=950),
        actor="avo",
        reason="new raw-based cut",
    )
    assert workspace.store("cmap").effective_approval() is None
    for artifact_type in ("bmap", "tracks", "animation"):
        index = workspace.store(artifact_type).load_index()
        assert index["activeState"] == "stale"
        assert any(ref["type"] == "invalidated" for ref in index["eventRefs"])
