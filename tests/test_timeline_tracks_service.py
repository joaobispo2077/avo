from __future__ import annotations

from pathlib import Path

import pytest

from avo.timeline.bmap_service import BMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.tracks import TrackError, TracksService
from tests.test_timeline_bmap_service import approved_workspace, cue


def canonical_tracks(workspace, source: Path) -> dict:
    fingerprint = file_fingerprint(source)
    common_region = {
        "regionId": "region-one",
        "startTicks": 100,
        "endTicks": 400,
        "cueIds": ["cue-one"],
    }
    return {
        "audioTracks": {
            "layers": [
                {
                    "layerId": "dialogue",
                    "order": 0,
                    "role": "dialogue",
                    "source": fingerprint,
                    "regions": [common_region],
                    "channels": [0, 1],
                    "gainDb": 0,
                    "mute": False,
                    "loudnessIntent": "dialogue lead",
                }
            ]
        },
        "videoTracks": {
            "layers": [
                {
                    "layerId": "base-video",
                    "order": 0,
                    "role": "base",
                    "source": fingerprint,
                    "regions": [common_region],
                    "zOrder": 0,
                    "fit": "contain",
                    "safeZones": ["face", "captions"],
                    "faceAvoidance": True,
                }
            ]
        },
    }


def test_tracks_service_binds_exact_bmap_and_traces_layers(tmp_path: Path) -> None:
    workspace, _, _ = approved_workspace(tmp_path)
    bmap = BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="beat")
    source = workspace.raw_dir / "raw.bin"
    revision = TracksService(workspace).author(
        canonical_tracks(workspace, source),
        actor="avo",
        reason="resolve assembly",
    )
    assert revision["snapshot"]["basis"]["revisionId"] == bmap["revisionId"]
    report = TracksService(workspace).inspect()
    assert report["audioLayers"][0]["layerId"] == "dialogue"
    assert report["videoLayers"][0]["layerId"] == "base-video"


def test_tracks_source_and_timing_mismatch_block(tmp_path: Path) -> None:
    workspace, _, _ = approved_workspace(tmp_path)
    BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="beat")
    source = workspace.raw_dir / "raw.bin"
    value = canonical_tracks(workspace, source)
    value["audioTracks"]["layers"][0]["regions"][0]["startTicks"] = 200
    with pytest.raises(TrackError, match="timing"):
        TracksService(workspace).author(value, actor="avo", reason="bad")
    value = canonical_tracks(workspace, source)
    source.write_bytes(b"changed")
    with pytest.raises(TrackError, match="fingerprint"):
        TracksService(workspace).author(value, actor="avo", reason="bad")


def test_author_refreshes_editlog_audio_layer(tmp_path: Path) -> None:
    workspace, _, _ = approved_workspace(tmp_path)
    BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="beat")
    source = workspace.raw_dir / "raw.bin"
    revision = TracksService(workspace).author(
        canonical_tracks(workspace, source),
        actor="avo",
        reason="resolve assembly",
    )
    assert revision["editlogRefresh"]["ok"] is True
    text = (workspace.raw_dir / "EDITLOG.md").read_text(encoding="utf-8")
    assert "dialogue" in text
    assert "`dialogue`" in text
