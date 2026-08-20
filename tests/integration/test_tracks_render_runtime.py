from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.fixtures.timeline.build_fixtures import build_fixture_set
from tests.integration.test_cmap_cut_review_runtime import _snapshot, _workspace
from tests.test_timeline_review_integration import FakeQc, FakeTranscript, FakeWatch

from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.timeline.approval_service import ApprovalService
from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.materialize import materialize_cut_proof
from avo.timeline.projection import write_assembly_projection
from avo.timeline.review_runner import ReviewRunner
from avo.timeline.sync_service import SyncService
from avo.timeline.tracks import TracksService


def tv(ticks):
    return {
        "ticks": ticks,
        "timebase": {"num": 1, "den": 1000},
        "domain": "cmap-output",
    }


def make_cue(cue_id, kind, start, end, layer):
    return {
        "cueId": cue_id,
        "start": tv(start),
        "end": tv(end),
        "kind": kind,
        "contentRef": {},
        "targetLayerId": layer,
        "intent": "support the current spoken idea",
        "reason": "fixture assembly trace",
        "reviewState": "pending",
    }


def source(path: Path):
    return file_fingerprint(path)


def region(region_id, start, end, cue_id, **extra):
    return {
        "regionId": region_id,
        "startTicks": start,
        "endTicks": end,
        "cueIds": [cue_id],
        **extra,
    }


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
def test_encoded_multilayer_tracks_render_and_trace(tmp_path: Path) -> None:
    raw_dir = tmp_path / "project"
    raw_dir.mkdir()
    build_fixture_set(raw_dir)
    source_a = raw_dir / "source-a.mp4"
    source_b = raw_dir / "source-b.mp4"
    workspace = _workspace(raw_dir)
    sync = SyncService(workspace)
    sync_revision = sync.author_not_applicable(
        raw_fingerprints={
            "source-a": source(source_a)["sha256"],
            "source-b": source(source_b)["sha256"],
        },
        actor="avo",
        reason="single embedded clocks",
    )
    evidence = sync.validate_current()
    sync.decide(
        decision="approved",
        candidate_hash=sync_revision["contentHash"],
        evidence_bundle_hash=evidence["sha256"],
        actor="creator",
        reason="sync n/a approved",
    )
    cmap_revision = CMapService(workspace).author(
        _snapshot(source_a, source_b, second=True),
        actor="avo",
        reason="two-second cut",
    )
    cut = materialize_cut_proof(
        workspace=workspace,
        cmap_revision_id=cmap_revision["revisionId"],
        output_path=raw_dir / "edit" / "cut.mp4",
    )
    cut_review = ReviewRunner(
        review_root=workspace.review_dir,
        transcription=FakeTranscript(),
        watch=FakeWatch(),
        deterministic_qc=FakeQc(),
        workspace=workspace,
        clock=lambda: "2026-08-13T00:00:00Z",
    ).run(
        checkpoint="cut-proof",
        candidate=Path(cut["output"]["locator"]),
        dependencies={
            "cmap": cmap_revision["contentHash"],
            "sync-map": cmap_revision["snapshot"]["syncRef"]["contentSha256"],
            "cutOutput": cut["output"]["sha256"],
        },
        render_profile="draft",
        risk_windows=[{"start": 0.9, "end": 1.1, "reason": "join"}],
    )
    cut_record = (
        workspace.timeline_dir
        / "materializations"
        / "cut-proof"
        / f"{cut['materializationId']}.json"
    )
    ApprovalService(workspace).decide(
        decision="approved",
        revision_id=cmap_revision["revisionId"],
        review_path=cut_review["reviewPath"],
        materialization_path=cut_record,
        actor="creator",
        reason="approve exact cut",
    )

    cues = [
        make_cue("cue-dialogue", "text", 0, 2000, "dialogue"),
        make_cue("cue-music-a", "music", 0, 650, "music-a"),
        make_cue("cue-music-b", "music", 650, 1300, "music-b"),
        make_cue("cue-music-c", "music", 1300, 2000, "music-c"),
        make_cue("cue-sfx", "sfx", 500, 800, "sfx"),
        make_cue("cue-ambience", "ambience", 0, 2000, "ambience"),
        make_cue("cue-clip", "clip", 200, 600, "clip"),
        make_cue("cue-image", "insert", 600, 900, "image"),
        make_cue("cue-text", "text", 900, 1200, "text"),
        make_cue("cue-card", "card", 1200, 1500, "card"),
        make_cue("cue-graphic", "insert", 1500, 1800, "graphic"),
        make_cue("cue-caption", "caption", 0, 2000, "captions"),
    ]
    BMapService(workspace).author(
        {"cues": cues}, actor="avo", reason="resolved beat map"
    )

    captions = raw_dir / "captions.srt"
    captions.write_text(
        "1\n00:00:00,100 --> 00:00:01,900\nTimeline Tracks\n", encoding="utf-8"
    )
    audio_layers = [
        {
            "layerId": "dialogue",
            "order": 0,
            "role": "dialogue",
            "source": source(Path(cut["output"]["locator"])),
            "regions": [region("region-dialogue", 0, 2000, "cue-dialogue")],
            "channels": [0, 1],
            "gainDb": 0,
            "mute": False,
        },
        {
            "layerId": "music-a",
            "order": 1,
            "role": "music",
            "source": source(source_a),
            "regions": [region("region-music-a", 0, 650, "cue-music-a")],
            "gainDb": -24,
            "ducking": {"amountDb": 8},
            "fades": {"inTicks": 80, "outTicks": 80},
        },
        {
            "layerId": "music-b",
            "order": 2,
            "role": "music",
            "source": source(source_b),
            "regions": [region("region-music-b", 650, 1300, "cue-music-b")],
            "gainDb": -24,
            "ducking": {"amountDb": 8},
        },
        {
            "layerId": "music-c",
            "order": 3,
            "role": "music",
            "source": source(source_a),
            "regions": [region("region-music-c", 1300, 2000, "cue-music-c")],
            "gainDb": -24,
            "ducking": {"amountDb": 8},
        },
        {
            "layerId": "sfx",
            "order": 4,
            "role": "sfx",
            "source": source(source_b),
            "regions": [region("region-sfx", 500, 800, "cue-sfx")],
            "gainDb": -14,
        },
        {
            "layerId": "ambience",
            "order": 5,
            "role": "ambience",
            "source": source(source_a),
            "regions": [region("region-ambience", 0, 2000, "cue-ambience")],
            "gainDb": -32,
        },
    ]
    visual_defs = [
        (
            "base-video",
            "base",
            0,
            0,
            2000,
            "cue-dialogue",
            Path(cut["output"]["locator"]),
        ),
        ("clip", "clip", 10, 200, 600, "cue-clip", source_b),
        ("image", "image", 20, 600, 900, "cue-image", source_a),
        ("text", "text", 30, 900, 1200, "cue-text", source_b),
        ("card", "card", 40, 1200, 1500, "cue-card", source_a),
        ("graphic", "graphic", 50, 1500, 1800, "cue-graphic", source_b),
        ("captions", "caption", 100, 0, 2000, "cue-caption", captions),
    ]
    video_layers = [
        {
            "layerId": layer_id,
            "order": ordinal,
            "role": role,
            "source": source(path),
            "regions": [region(f"region-{layer_id}", start, end, cue_id)],
            "zOrder": z,
            "fit": "contain",
            "safeZones": ["face", "captions"],
            "faceAvoidance": True,
        }
        for ordinal, (layer_id, role, z, start, end, cue_id, path) in enumerate(
            visual_defs
        )
    ]
    tracks = TracksService(workspace).author(
        {
            "audioTracks": {"layers": audio_layers},
            "videoTracks": {"layers": video_layers},
        },
        actor="avo",
        reason="full inspectable assembly",
    )
    projection, manifest = write_assembly_projection(workspace)
    assert "music-beds" in manifest["capabilities"]
    edl = json.loads(projection.read_text(encoding="utf-8"))
    assert "resolved_tracks" not in edl
    assert "timeline_tracks" in edl
    assert "sound_effects" not in edl

    output = raw_dir / "edit" / "tracks-preview.mp4"
    rendered = TimelineRenderAdapter().render(projection, output, profile="preview")
    assert output.is_file() and rendered["output"]["sha256"] == source(output)["sha256"]
    probe = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert {item["codec_type"] for item in probe["streams"]} == {"video", "audio"}
    report = TracksService(workspace).inspect()
    assert len(report["audioLayers"]) == 6
    assert len(report["videoLayers"]) == 7
