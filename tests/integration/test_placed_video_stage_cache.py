"""Physical native microproofs retain original pixels while reusing video stages."""

import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from tests.integration.test_otio_placed_render_runtime import (
    _encode,
    _execution,
    _picture_values,
    _source,
)
from tests.test_timeline_import_layout import placed_snapshot, raw_time

from avo.adapters.media import proof_executor, proof_placed
from avo.capabilities import default_proof_capability_registry
from avo.timeline.contracts import ContractError, content_hash
from avo.timeline.initial_cut_placed import placed_cut_proof_request
from avo.timeline.proof_validation_stage import proof_validation_batch

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Actual FFmpeg/FFprobe required",
)


def _frozen_identity(execution):
    execution["canonicalInputLock"].update(
        {
            name: content_hash({"synthetic-physical-test-head": name})
            for name in ("cmap", "bmap", "tracks", "animation", "sync-map")
        }
    )
    execution["proofPlanHash"] = content_hash(execution)
    return execution


def _thirty_to_sixty(tmp_path, *, end_gap=False):
    source = tmp_path / "source30.mkv"
    values = _picture_values(0, 10 if end_gap else 48)
    _encode(source, values, fps="30")
    if end_gap:
        shifted = tmp_path / "source30-gap.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
                "-bsf:v",
                "setts=pts=PTS+67*gte(N\\,9):dts=DTS+67*gte(N\\,9)",
                str(shifted),
            ],
            check=True,
            capture_output=True,
        )
        source = shifted
    snapshot = placed_snapshot()
    snapshot["sources"] = [_source("camera", source)]
    rate, base = {"num": 60, "den": 1}, {"num": 1, "den": 60}
    snapshot["importOutput"]["frameRate"] = rate
    layout = snapshot["layout"]
    layout["programClock"].update(frameRate=rate, timebase=base)
    extent = 48 if end_gap else 96
    layout["duration"] = {"ticks": extent, "timebase": base, "domain": "cmap-output"}
    layout["tracks"] = layout["tracks"][:1]
    picture = layout["placements"][0]
    picture.update(
        **{
            "in": raw_time(0 if end_gap else 3, "camera", den=30),
            "out": raw_time(12 if end_gap else 39, "camera", den=30),
        },
        start={"ticks": 12, "timebase": base, "domain": "cmap-output"},
        end={"ticks": 36 if end_gap else 84, "timebase": base, "domain": "cmap-output"},
        pictureSampling="repeat-2x",
        pictureFade={"inFrames": 4, "outFrames": 6},
    )
    if end_gap:
        picture["pictureEndGapFrames"] = 2
    layout["placements"], layout["gaps"] = [picture], []
    execution = placed_cut_proof_request(
        SimpleNamespace(raw_dir=tmp_path),
        snapshot,
        iteration_id="physical-cache",
        output=tmp_path / "planned.mkv",
        frame_rate=rate,
        width=64,
        height=48,
        sample_rate=48000,
        sample_rate_probe=None,
    )
    implementation = default_proof_capability_registry().resolve("source-layout")
    execution["videoGraph"]["operations"][0]["implementationId"] = (
        implementation.implementation_id
    )
    execution.update(
        window=None,
        sourceAssemblyPolicy="preserve-import",
        implementationRefs=[implementation.proof_reference()],
        canonicalInputLock={
            "source:camera": snapshot["sources"][0]["fingerprint"]["sha256"]
        },
    )
    execution["output"].update(
        videoCodec="ffv1", audioCodec="pcm_s32le", conformance=True
    )
    return _frozen_identity(execution), source


def _rgba(path):
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-pix_fmt",
            "rgba",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 48, 64, 4)


def _render(execution, output, first, last):
    request = deepcopy(execution)
    request["window"] = {"startFrame": first, "endFrameExclusive": last}
    return proof_executor.execute_ffmpeg_proof(request, output)


def _trace_full_stages(monkeypatch):
    original, calls = proof_placed._stage_picture, []

    def traced(source, output, *args, **kwargs):
        calls.append((source["item"]["mediaKind"], kwargs.get("stop_frame")))
        return original(source, output, *args, **kwargs)

    monkeypatch.setattr(proof_placed, "_stage_picture", traced)
    return calls


def test_cached_late_and_overlapping_windows_match_every_direct_rgba_frame(
    tmp_path, monkeypatch
):
    execution, _ = _thirty_to_sixty(tmp_path)
    full = tmp_path / "full.mkv"
    proof_executor.execute_ffmpeg_proof(execution, full)
    expected = _rgba(full)
    assert expected[12, 0, 0, 0] == 0
    assert expected[30, 0, 0, 0] > expected[83, 0, 0, 0]
    windows = [(10, 30), (55, 83), (70, 96)]
    for index, (first, last) in enumerate(windows):
        direct = tmp_path / f"direct-{index}.mkv"
        _render(execution, direct, first, last)
        assert np.array_equal(_rgba(direct), expected[first:last])
    calls = _trace_full_stages(monkeypatch)
    with proof_validation_batch(reuse_video_stages=True):
        for index, (first, last) in enumerate(windows):
            output = tmp_path / f"cached-{index}.mkv"
            _render(execution, output, first, last)
            assert np.array_equal(_rgba(output), expected[first:last])
        directories = list(tmp_path.glob("placed-video-stages-*"))
        assert len(directories) == 1
        assert len(list(directories[0].glob("stage-*.mkv"))) == 1
    assert calls == [("video", None)]
    assert not directories[0].exists()


def test_cached_end_gap_and_fades_retain_the_exact_tail(tmp_path):
    execution, _ = _thirty_to_sixty(tmp_path, end_gap=True)
    full = tmp_path / "gap-full.mkv"
    proof_executor.execute_ffmpeg_proof(execution, full)
    with proof_validation_batch(reuse_video_stages=True):
        output = tmp_path / "gap-window.mkv"
        _render(execution, output, 27, 40)
        assert np.array_equal(_rgba(output), _rgba(full)[27:40])


def test_stage_lifetime_is_one_batch_and_full_build_bypasses_stage_cache(
    tmp_path, monkeypatch
):
    execution, _ = _thirty_to_sixty(tmp_path)
    calls = _trace_full_stages(monkeypatch)
    for index in range(2):
        _render(execution, tmp_path / f"outside-{index}.mkv", 55, 83)
    assert calls == [("video", 83), ("video", 83)]
    calls.clear()
    with proof_validation_batch():
        _render(execution, tmp_path / "default-batch.mkv", 55, 83)
    assert calls == [("video", 83)]
    assert not list(tmp_path.glob("placed-video-stages-*"))
    calls.clear()
    for index in range(2):
        with proof_validation_batch(reuse_video_stages=True):
            _render(execution, tmp_path / f"batch-{index}.mkv", 55, 83)
        assert not list(tmp_path.glob("placed-video-stages-*"))
    assert calls == [("video", None), ("video", None)]
    calls.clear()
    from avo.adapters.media import proof_bounded

    decodes = []
    original = proof_placed._picture_arguments

    def trace_decoder(source, *args, **kwargs):
        decodes.append(source["item"]["placementId"])
        return original(source, *args, **kwargs)

    monkeypatch.setattr(proof_placed, "_picture_arguments", trace_decoder)
    monkeypatch.setattr(proof_bounded, "MAX_CHUNK_FRAMES", 11)
    with proof_validation_batch(reuse_video_stages=True):
        proof_executor.execute_ffmpeg_proof(execution, tmp_path / "full-inside.mkv")
    assert calls == []
    assert len(decodes) == 1
    assert not list(tmp_path.glob("placed-video-stages-*"))


@pytest.mark.parametrize("changed", ["plan", "canonical", "fade"])
def test_stage_never_crosses_its_plan_or_placement_key(tmp_path, monkeypatch, changed):
    execution, _ = _thirty_to_sixty(tmp_path)
    alternate = deepcopy(execution)
    if changed == "plan":
        alternate["proofPlanHash"] = "f" * 64
    elif changed == "canonical":
        alternate["canonicalInputLock"]["bmap"] = "f" * 64
    else:
        alternate["videoGraph"]["operations"][0]["parameters"]["placements"][0][
            "pictureFade"
        ]["outFrames"] = 8
    calls = _trace_full_stages(monkeypatch)
    with proof_validation_batch(reuse_video_stages=True):
        _render(execution, tmp_path / "first-key.mkv", 55, 83)
        _render(alternate, tmp_path / "second-key.mkv", 55, 83)
    assert calls == [("video", None), ("video", None)]


@pytest.mark.parametrize("changed", ["source", "cache"])
@pytest.mark.parametrize("operation", ["mutate", "delete"])
def test_closing_guard_rejects_source_or_cache_change_and_still_cleans_resources(
    tmp_path, changed, operation
):
    execution, source = _thirty_to_sixty(tmp_path)
    path, original = None, None
    try:
        with pytest.raises((ContractError, RuntimeError), match="changed|missing"):
            with proof_validation_batch(reuse_video_stages=True):
                _render(execution, tmp_path / "before-change.mkv", 55, 83)
                path = (
                    source
                    if changed == "source"
                    else next(tmp_path.glob("placed-video-stages-*/stage-*.mkv"))
                )
                original = path.read_bytes()
                if operation == "delete":
                    path.unlink()
                else:
                    path.write_bytes(original + b"changed-after-last-window")
    finally:
        if path == source and original is not None:
            path.write_bytes(original)
    assert not list(tmp_path.glob("placed-video-stages-*"))


def test_modified_cache_is_rejected_before_next_window(tmp_path):
    execution, _ = _thirty_to_sixty(tmp_path)
    target = tmp_path / "must-not-publish.mkv"
    with pytest.raises(RuntimeError, match="cache file changed"):
        with proof_validation_batch(reuse_video_stages=True):
            _render(execution, tmp_path / "before-change.mkv", 55, 83)
            cache = next(tmp_path.glob("placed-video-stages-*/stage-*.mkv"))
            cache.write_bytes(cache.read_bytes() + b"changed")
            _render(execution, target, 70, 96)
    assert not target.exists()


def test_insufficient_space_falls_back_without_an_eager_full_stage(
    tmp_path, monkeypatch
):
    execution, _ = _thirty_to_sixty(tmp_path)
    direct = tmp_path / "bounded-direct.mkv"
    _render(execution, direct, 55, 83)
    calls = _trace_full_stages(monkeypatch)
    monkeypatch.setattr(
        proof_placed.shutil, "disk_usage", lambda _: SimpleNamespace(free=0)
    )
    with proof_validation_batch(reuse_video_stages=True):
        output = tmp_path / "bounded-fallback.mkv"
        _render(execution, output, 55, 83)
        assert np.array_equal(_rgba(output), _rgba(direct))
    assert calls == [("video", 83)]
    assert not list(tmp_path.glob("placed-video-stages-*"))


def test_literal_still_does_not_enter_video_cache(tmp_path, monkeypatch):
    execution, _ = _execution(tmp_path)
    _frozen_identity(execution)
    calls = _trace_full_stages(monkeypatch)
    with proof_validation_batch(reuse_video_stages=True):
        _render(execution, tmp_path / "still-only.mkv", 55, 60)
    assert calls == [("still", 60)]
    assert not list(tmp_path.glob("placed-video-stages-*"))


def test_cleanup_refuses_a_resolved_root_redirect_without_deleting_either_tree(
    tmp_path, monkeypatch
):
    directory, outside = tmp_path / "owned-stage", tmp_path / "outside"
    directory.mkdir()
    outside.mkdir()
    (directory / "owned.txt").write_text("keep owned")
    (outside / "unrelated.txt").write_text("keep unrelated")
    original = Path.resolve

    def redirect(path, *args, **kwargs):
        return outside if path == directory else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirect)
    with pytest.raises(RuntimeError, match="Unsafe.*cleanup target"):
        proof_placed._remove_stage_cache_directory(directory, directory, tmp_path)
    assert (directory / "owned.txt").read_text() == "keep owned"
    assert (outside / "unrelated.txt").read_text() == "keep unrelated"


def test_cleanup_preserves_an_unexpected_nested_directory(tmp_path):
    directory = tmp_path / "owned-stage"
    nested = directory / "unexpected"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_text("keep unknown descendants")
    with pytest.raises(RuntimeError, match="Unsafe.*descendant"):
        proof_placed._remove_stage_cache_directory(directory, directory, tmp_path)
    assert (nested / "keep.txt").read_text() == "keep unknown descendants"


def test_cleanup_rejects_a_native_directory_link_escape(tmp_path):
    directory, outside = tmp_path / "owned-stage", tmp_path / "outside"
    directory.mkdir()
    outside.mkdir()
    (outside / "keep.txt").write_text("keep unrelated")
    link = directory / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Native directory link permission unavailable: {error}")
    try:
        with pytest.raises(RuntimeError, match="Unsafe.*descendant"):
            proof_placed._remove_stage_cache_directory(directory, directory, tmp_path)
        assert directory.is_dir()
        assert (outside / "keep.txt").read_text() == "keep unrelated"
    finally:
        link.unlink()
