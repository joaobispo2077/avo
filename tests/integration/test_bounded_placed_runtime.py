"""Bounded full proofs retain the legacy renderer's exact picture and PCM clock."""

import shutil
from copy import deepcopy

import numpy as np
import pytest
from tests.integration.test_otio_generated_overlay_runtime import (
    add_overlay,
    placed_assets,
)
from tests.integration.test_otio_placed_render_runtime import (
    _decoded,
    _encode,
    _picture_values,
)
from tests.integration.test_otio_title_runtime import FONT
from tests.integration.test_placed_video_stage_cache import _rgba, _thirty_to_sixty

from avo.adapters.media.proof_executor import execute_ffmpeg_proof
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_layout import picture_input_ids

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
        reason="Actual FFmpeg/FFprobe required",
    ),
]

bounded_assets = pytest.fixture(name="bounded_assets")(placed_assets.__wrapped__)


def _small_chunks(monkeypatch):
    from avo.adapters.media import proof_bounded

    monkeypatch.setattr(proof_bounded, "MAX_CHUNK_FRAMES", 11)


def _compare_routes(execution, directory, *, total_frames, total_samples):
    original = deepcopy(execution)
    legacy = deepcopy(execution)
    legacy["window"] = {"startFrame": 0, "endFrameExclusive": total_frames}
    bounded = deepcopy(execution)
    bounded["window"] = None
    legacy_path, bounded_path = directory / "legacy.mkv", directory / "bounded.mkv"
    execute_ffmpeg_proof(legacy, legacy_path)
    execute_ffmpeg_proof(bounded, bounded_path)
    picture, expected = _rgba(bounded_path), _rgba(legacy_path)
    audio, expected_audio = (
        _decoded(path, audio=True) for path in (bounded_path, legacy_path)
    )
    assert picture.shape == expected.shape == (total_frames, 48, 64, 4)
    assert audio.shape == expected_audio.shape == (total_samples, 2)
    assert np.array_equal(picture, expected)
    assert np.array_equal(audio, expected_audio)
    assert execution == original
    assert legacy["window"] == {"startFrame": 0, "endFrameExclusive": total_frames}
    assert bounded["window"] is None
    return picture, audio


def _add_title(execution, directory):
    project, font = directory / "title.json", directory / "title.ttf"
    project.write_text('{"text":"2026"}', encoding="utf-8")
    shutil.copyfile(FONT, font)
    sources = {}
    for source_id, path in (("title-project", project), ("title-font", font)):
        fingerprint = file_fingerprint(path)
        execution["canonicalInputLock"][f"source:{source_id}"] = fingerprint["sha256"]
        sources[source_id] = {
            "locator": str(path),
            "sha256": fingerprint["sha256"],
            "mediaClass": "source",
            "ancestry": [],
        }
    operation = execution["videoGraph"]["operations"][0]
    operation["parameters"]["placements"].append(
        {
            "placementId": "bounded-title",
            "trackId": "title-track",
            "sourceId": "title-project",
            "mediaKind": "title",
            "source": sources["title-project"],
            "sourceRange": {
                "startTicks": 0,
                "endTicks": 28,
                "timebase": {"num": 1, "den": 24},
            },
            "outputRange": {"startFrame": 19, "endFrameExclusive": 47},
            "zOrder": 4,
            "enabled": True,
            "pictureFade": {"inFrames": 3, "outFrames": 7},
            "title": {
                "text": "2026",
                "canvasWidth": 64,
                "canvasHeight": 48,
                "x": 32,
                "y": 24,
                "fontSize": 12,
                "color": "#FFFFFFFF",
                "anchor": "center",
            },
            "fontSource": {"sourceId": "title-font", "source": sources["title-font"]},
        }
    )
    operation["inputs"] = picture_input_ids(operation["parameters"]["placements"])


@pytest.mark.skipif(FONT is None, reason="Installed native title font required")
def test_bounded_full_matches_layered_title_privacy_gas_and_pcm(
    bounded_assets, tmp_path, monkeypatch
):
    _small_chunks(monkeypatch)
    execution, assets = bounded_assets
    layout = execution["videoGraph"]["operations"][0]["parameters"]
    for item in layout["placements"]:
        item["pictureFade"] = {"inFrames": 2, "outFrames": 3}
        if item["mediaKind"] == "still":
            item["pictureTransform"] = {
                "canvasWidth": 64,
                "canvasHeight": 48,
                "x": 40,
                "y": 30,
                "width": 16,
                "height": 12,
            }
    _add_title(execution, tmp_path)
    layout["privacyMasks"] = {
        "canvasWidth": 64,
        "canvasHeight": 48,
        "regions": [
            {
                "maskId": "bounded-account-name",
                "startFrame": 29,
                "endFrameExclusive": 37,
                "x": 2,
                "y": 2,
                "width": 4,
                "height": 4,
            }
        ],
    }
    add_overlay(execution, assets["alpha"], start=7, end=61, local_start=7)
    execution["videoGraph"]["operations"].reverse()
    picture, audio = _compare_routes(
        execution, tmp_path, total_frames=96, total_samples=192000
    )
    # Independent sentinels prevent two identically wrong routes from passing.
    assert np.all(picture[:7, :, :, :3] == 0)
    assert tuple(picture[10, 11, 13, :3]) == (60, 200, 35)
    assert np.any(picture[28, 3, 3, :3])
    assert np.all(picture[29:37, 3, 3, :3] == 0)
    assert np.any(picture[37, 3, 3, :3])
    assert tuple(picture[60, 35, 45, :3]) == (0, 180, 0)
    assert np.all(picture[66:72, :, :, :3] == 0)
    assert np.any(picture[95, :, :, :3])
    assert np.any(audio[48000:96000])
    assert np.all(audio[:48000] == 0)


def test_bounded_full_preserves_repeat_two_fades_and_bounded_end_gap(
    tmp_path, monkeypatch
):
    _small_chunks(monkeypatch)
    execution, _ = _thirty_to_sixty(tmp_path, end_gap=True)
    picture, audio = _compare_routes(
        execution, tmp_path, total_frames=48, total_samples=38400
    )
    assert np.all(picture[:12, :, :, :3] == 0)
    assert np.all(picture[36:, :, :, :3] == 0)
    assert np.array_equal(picture[18], picture[19])
    assert np.array_equal(picture[22], picture[23])
    assert np.sum(picture[35, :, :, :3]) < np.sum(picture[30, :, :, :3])
    assert np.any(picture[35, :, :, :3])
    assert np.all(audio == 0)


@pytest.mark.parametrize("full", [False, True], ids=["legacy-window", "bounded-full"])
def test_source_eof_cannot_publish_a_partial_bounded_proof(tmp_path, monkeypatch, full):
    _small_chunks(monkeypatch)
    execution, _ = _thirty_to_sixty(tmp_path)
    truncated = tmp_path / "short-source.mkv"
    _encode(truncated, _picture_values(0, 35), fps="30")
    source = execution["videoGraph"]["operations"][0]["parameters"]["placements"][0][
        "source"
    ]
    fingerprint = file_fingerprint(truncated)
    source.update(locator=str(truncated), sha256=fingerprint["sha256"])
    execution["canonicalInputLock"]["source:camera"] = fingerprint["sha256"]
    execution["window"] = None if full else {"startFrame": 0, "endFrameExclusive": 96}
    output = tmp_path / "must-not-publish.mkv"
    with pytest.raises(
        RuntimeError, match="available picture frames|EOF|frame contract"
    ):
        execute_ffmpeg_proof(execution, output)
    assert not output.exists()
