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


def _code_drawn_source(workspace, *, instance_id="instance-overlay"):
    import json

    from avo import motion
    from avo.timeline.contracts import file_fingerprint

    directory = workspace.raw_dir / "edit/derived/components" / instance_id
    motion.scaffold_code_drawn(
        directory,
        route="canvas",
        width=128,
        height=96,
        fps="30/1",
        frames=9,
        background="transparent",
    )
    composition = directory / "composition.json"
    manifest = json.loads(composition.read_text(encoding="utf-8"))
    manifest["compositionId"] = instance_id
    composition.write_text(
        json.dumps(motion.seal_composition(manifest)), encoding="utf-8"
    )
    return {
        "instanceId": instance_id,
        "manifestRef": {
            "path": composition.relative_to(workspace.raw_dir).as_posix(),
            "sha256": file_fingerprint(composition)["sha256"],
        },
    }


def code_drawn_workspace(tmp_path):
    from copy import deepcopy

    workspace, _, _ = approved_workspace(tmp_path)
    value = cue()
    value["kind"] = "animation"
    BMapService(workspace).author(
        {"cues": [value]}, actor="avo", reason="frozen graphic cue"
    )
    reference = _code_drawn_source(workspace)
    tracks = canonical_tracks(workspace, workspace.raw_dir / "raw.bin")
    tracks["videoTracks"]["layers"].append(
        {
            "layerId": "graphics",
            "order": 1,
            "role": "overlay",
            "generatedSourceRef": {"engine": "code-drawn", **deepcopy(reference)},
            "regions": [
                {
                    "regionId": "region-graphic",
                    "startTicks": 100,
                    "endTicks": 400,
                    "cueIds": ["cue-one"],
                }
            ],
            "zOrder": 10,
            "fit": "none",
            "placement": {"x": 0, "y": 0, "width": 128, "height": 96},
            "safeZones": ["face", "captions"],
            "captionAvoidance": True,
            "animationRef": "chapter-pair",
        }
    )
    TracksService(workspace).author(
        tracks, actor="avo", reason="logical generated placement"
    )
    value = strategy()
    value["framework"] = "code-drawn"
    value["components"][0].pop("providerPatternRef")
    value["components"][0]["extensions"] = {"codeDrawn": reference}
    revision = AnimationService(workspace).author(
        value, actor="avo", reason="authored drawing source"
    )
    return workspace, revision, reference


def test_saved_default_change_preserves_existing_approved_code_drawn_source(tmp_path):
    from avo.motion import set_motion_preference

    workspace, revision, _ = code_drawn_workspace(tmp_path)
    store = workspace.store("animation")
    store.approve(
        revision["revisionId"],
        revision_hash=revision["contentHash"],
        candidate_hash=revision["contentHash"],
    )
    approval = store.effective_approval()
    before = {
        path: path.read_bytes()
        for path in workspace.timeline_dir.rglob("*")
        if path.is_file()
    }
    result = set_motion_preference(
        scope="project",
        engine="hyperframes",
        project=workspace.project_path,
        home=tmp_path / "isolated-home",
    )
    assert result["selection"]["engine"] == "hyperframes"
    assert result["recordedAnimation"]["framework"] == "code-drawn"
    assert result["recordedAnimation"]["sha256"] == revision["contentHash"]
    assert store.effective_approval() == approval
    assert {path: path.read_bytes() for path in before} == before


def test_deliberate_new_engine_source_creates_revision_and_stales_old_approval_only(
    tmp_path,
):
    workspace, _, _ = approved_workspace(tmp_path)
    BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="beat")
    TracksService(workspace).author(
        canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
        actor="avo",
        reason="tracks",
    )
    service = AnimationService(workspace)
    original = service.author(
        strategy(), actor="avo", reason="original HyperFrames source"
    )
    service.store.approve(
        original["revisionId"],
        revision_hash=original["contentHash"],
        candidate_hash=original["contentHash"],
    )
    before = workspace.active_dependency_snapshot()
    approval = workspace.store("cmap").effective_approval()
    value = strategy()
    value["framework"] = "code-drawn"
    value["components"][0].pop("providerPatternRef")
    value["components"][0]["extensions"] = {"codeDrawn": _code_drawn_source(workspace)}
    revised = service.author(
        value, actor="creator", reason="deliberately authored compatible drawing"
    )
    assert revised["revisionId"] != original["revisionId"]
    assert revised["contentHash"] != original["contentHash"]
    assert service.store.effective_approval() is None
    assert (
        service.store.revision(original["revisionId"])["contentHash"]
        == original["contentHash"]
    )
    after = workspace.active_dependency_snapshot()
    assert {key: value for key, value in before.items() if key != "animation"} == {
        key: value for key, value in after.items() if key != "animation"
    }
    assert workspace.store("cmap").effective_approval() == approval


def test_code_drawn_does_not_automatically_relabel_a_hyperframes_provider_kit(tmp_path):
    workspace, _, _ = approved_workspace(tmp_path)
    BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="beat")
    TracksService(workspace).author(
        canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
        actor="avo",
        reason="tracks",
    )
    value = strategy()
    value["framework"] = "code-drawn"
    before = workspace.store("animation").load_index()
    with pytest.raises(
        AnimationError, match="code-drawn|compatible|manifest|HyperFrames"
    ):
        AnimationService(workspace).author(
            value, actor="avo", reason="unsupported kit must block"
        )
    assert workspace.store("animation").load_index() == before
