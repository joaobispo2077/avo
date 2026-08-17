from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.workspace import TimelineWorkspace, WorkspaceError


def project(tmp_path: Path, *, canonical: bool = True) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    payload = {
        "provider": "bishop",
        "rawDir": str(root),
        "timeline": {
            "directory": "edit/timeline",
            "generatedEdlPath": "edit/edl.json",
            "canonicalFirst": canonical,
            "migration": {
                "allowLegacyEdlFallback": True,
                "warnOnDerivedEdlMismatch": True,
            },
        },
    }
    path = root / "avo.project.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_workspace_resolves_canonical_and_legacy_authority(tmp_path: Path) -> None:
    path = project(tmp_path)
    ws = TimelineWorkspace.from_project(path, video_id="video")
    assert ws.authority == "legacy"
    ws.initialize(provider="bishop")
    assert ws.authority == "canonical"
    assert ws.status()["artifacts"]["cmap"]["headRevisionId"] is None


def test_derived_edl_mismatch_blocks_canonical_workspace(tmp_path: Path) -> None:
    path = project(tmp_path)
    ws = TimelineWorkspace.from_project(path, video_id="video")
    ws.initialize(provider="bishop")
    edl = ws.raw_dir / "edit" / "edl.json"
    edl.parent.mkdir(parents=True, exist_ok=True)
    edl.write_text("{}", encoding="utf-8")
    projection = ws.timeline_dir / "projection.json"
    projection.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "canonicalDirectory": "edit/timeline",
                "generatedEdlPath": "edit/edl.json",
                "canonicalFirst": True,
                "status": "generated",
                "edlSha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(WorkspaceError, match="derived EDL"):
        ws.validate()


def test_review_change_summary_uses_exact_revision_diff_and_stale_state(
    tmp_path: Path,
) -> None:
    path = project(tmp_path)
    workspace = TimelineWorkspace.from_project(path, video_id="video")
    workspace.initialize(provider="bishop")
    cmap = workspace.store("cmap").append_revision(
        snapshot={"segments": [{"segmentId": "segment-one"}]},
        actor="agent",
        reason="remove idle pause without changing meaning",
        diff=[
            {
                "opId": "diff-0001",
                "op": "replace",
                "target": {"collection": "segments", "stableId": "segment-one"},
                "reason": "remove idle pause without changing meaning",
                "actorIntent": "preserve meaning",
                "affectedTimeRanges": [],
            }
        ],
    )
    workspace.store("bmap").append_revision(
        snapshot={"cues": []},
        actor="agent",
        reason="old beat map",
    )
    workspace.store("bmap").set_active_state(
        "stale",
        reason="CMap changed",
        actor="test",
    )
    windows = [{"start": 1.0, "end": 2.0, "reason": "cut edge"}]
    summary = workspace.review_change_summary(
        {"cmap": cmap["contentHash"]},
        windows=windows,
    )
    assert summary["headline"] == "cmap cmap-r0001: replace 1"
    assert summary["items"][0]["reason"] == "remove idle pause without changing meaning"
    assert summary["items"][0]["targets"] == ["segments:segment-one"]
    assert summary["windows"] == windows
    assert summary["staleDependencies"] == ["bmap"]
