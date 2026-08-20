from __future__ import annotations

from pathlib import Path

import pytest

from avo.timeline.animation import AnimationError, AnimationService
from avo.timeline.bmap_service import BMapService
from avo.timeline.tracks import TracksService
from tests.test_timeline_bmap_service import approved_workspace, cue
from tests.test_timeline_tracks_service import canonical_tracks


def strategy():
    return {
        "formatDiagnosis": {
            "format": "talking-head-review",
            "viewerIntent": "decide",
            "motionDensity": 2,
        },
        "density": 2,
        "safeZones": ["face", "captions"],
        "components": [
            {
                "componentId": "chapter-pair",
                "providerPatternRef": "c01-c02",
                "lifecycle": {
                    "preEntry": "hidden",
                    "entrance": "tremble",
                    "hold": "readable",
                    "exit": "resolve",
                },
                "accessibility": {"reducedMotion": "fade"},
            }
        ],
        "accessibility": {"reducedMotion": True, "flashingSafe": True},
        "framework": "hyperframes",
    }


def test_strategy_binds_exact_active_cmap_bmap_tracks(tmp_path: Path):
    workspace, _, _ = approved_workspace(tmp_path)
    BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="beat")
    TracksService(workspace).author(
        canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
        actor="avo",
        reason="tracks",
    )
    revision = AnimationService(workspace).author(
        strategy(), actor="avo", reason="motion strategy"
    )
    assert set(revision["snapshot"]["dependencies"]) == {"cmap", "bmap", "tracks"}


def test_strategy_rejects_timing_authority(tmp_path: Path):
    workspace, _, _ = approved_workspace(tmp_path)
    BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="beat")
    TracksService(workspace).author(
        canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
        actor="avo",
        reason="tracks",
    )
    value = strategy()
    value["components"][0]["startTicks"] = 100
    with pytest.raises(AnimationError, match="timing"):
        AnimationService(workspace).author(value, actor="avo", reason="bad")


def test_author_refreshes_editlog_motion(tmp_path: Path) -> None:
    workspace, _, _ = approved_workspace(tmp_path)
    BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="beat")
    TracksService(workspace).author(
        canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
        actor="avo",
        reason="tracks",
    )
    revision = AnimationService(workspace).author(
        strategy(), actor="avo", reason="motion strategy"
    )
    assert revision["editlogRefresh"]["ok"] is True
    text = (workspace.raw_dir / "EDITLOG.md").read_text(encoding="utf-8")
    assert "chapter-pair" in text
    assert "hyperframes" in text
