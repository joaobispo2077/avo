"""Exact native frame batches decode once and never trust stale image caches."""

from __future__ import annotations

import hashlib
import io
import shutil
import struct
import subprocess
import sys
import threading
import time
import zlib

import pytest

from avo.adapters.understand import watch_skill as watch
from avo.timeline.vision_review import VisionReviewError


def _chunk(kind: bytes, payload: bytes = b"") -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )


def _png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(b"\0\0\0\0"))
        + _chunk(b"IEND")
    )


class ShortReader(io.BytesIO):
    def read(self, size=-1):
        return super().read(min(size, 3))


def _single_frame_reference(candidate, frame, directory, long_side):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"reference-{frame}.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(candidate),
            "-map",
            "0:v:0",
            "-vf",
            f"select=eq(n\\,{frame}),scale={long_side}:{long_side}:force_original_aspect_ratio=decrease",
            "-vsync",
            "0",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path.read_bytes()


def test_png_parser_reads_fragmented_images_without_consuming_next():
    stream = ShortReader(_png() + _png())
    for _ in range(2):
        assert watch._read_frame_png(stream, max_bytes=1024, max_dimension=64) == _png()
    assert watch._read_frame_png(stream, max_bytes=1024, max_dimension=64) is None


@pytest.mark.parametrize(
    "damage", ["signature", "crc", "truncated", "oversize", "header", "no-data"]
)
def test_png_parser_fails_closed_on_malformed_or_oversize_frames(damage):
    value = _png()
    if damage == "signature":
        value = b"not-a-png" + value[8:]
    elif damage == "crc":
        value = value[:-1] + bytes([value[-1] ^ 1])
    elif damage == "truncated":
        value = value[:-5]
    elif damage == "oversize":
        value = value[:8] + struct.pack(">I", 2**31) + b"IHDR"
    elif damage == "header":
        value = (
            value[:8]
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", 8192, 1, 8, 2, 0, 0, 0))
            + value[33:]
        )
    else:
        value = value[:33] + _chunk(b"IEND")
    with pytest.raises(VisionReviewError):
        watch._read_frame_png(io.BytesIO(value), max_bytes=1024, max_dimension=64)


@pytest.mark.parametrize("vfr", [False, True])
def test_batch_exact_frames_match_per_frame_bytes_and_need_one_decode(
    tmp_path, monkeypatch, vfr
):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg unavailable")
    source = tmp_path / "tiny.mkv"
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=64x48:rate=12",
    ]
    if vfr:
        command += ["-vf", "setpts=N*N/(12*TB)", "-vsync", "0"]
    subprocess.run(
        [*command, "-frames:v", "12", "-c:v", "ffv1", str(source)],
        check=True,
        capture_output=True,
    )
    selected = [0, 1, 4, 9]
    expected = {
        n: _single_frame_reference(source, n, tmp_path / "reference", 64)
        for n in selected
    }
    original_popen = watch.subprocess.Popen
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[0])
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(watch.subprocess, "Popen", counted)
    directory = tmp_path / "batch"
    hashes = watch._prefetch_exact_frames(source, [9, 1, 9, 4, 0], directory, 64)
    assert list(hashes) == selected
    for n in selected:
        path = directory / f"frame-{n:09d}.png"
        assert path.read_bytes() == expected[n]
        assert hashes[n] == hashlib.sha256(expected[n]).hexdigest()
    assert len(calls) == 1


def _fake_decoder(monkeypatch, output):
    class Decoder:
        stdout = io.BytesIO(output)

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            raise AssertionError("finished decoder must not be killed")

    monkeypatch.setattr(watch.subprocess, "Popen", lambda *args, **kwargs: Decoder())


@pytest.mark.parametrize("count", [0, 2])
def test_batch_rejects_missing_or_extra_frames(tmp_path, monkeypatch, count):
    _fake_decoder(monkeypatch, _png() * count)
    with pytest.raises(VisionReviewError):
        watch._prefetch_exact_frames(
            tmp_path / "source.mkv", [3], tmp_path / "frames", 64
        )


def test_batch_rechecks_cached_bytes_and_preserves_tampered_file(tmp_path, monkeypatch):
    directory = tmp_path / "frames"
    directory.mkdir()
    path = directory / "frame-000000003.png"
    tampered = _png()[:-1] + b"!"
    path.write_bytes(tampered)
    _fake_decoder(monkeypatch, _png())
    with pytest.raises(VisionReviewError, match="cache"):
        watch._prefetch_exact_frames(tmp_path / "source.mkv", [3], directory, 64)
    assert path.read_bytes() == tampered


def test_batch_accepts_verified_equal_cached_bytes_without_overwrite(
    tmp_path, monkeypatch
):
    directory = tmp_path / "frames"
    directory.mkdir()
    path = directory / "frame-000000003.png"
    path.write_bytes(_png())
    before = path.read_bytes(), path.stat().st_mtime_ns
    _fake_decoder(monkeypatch, _png())
    watch._prefetch_exact_frames(tmp_path / "source.mkv", [3], directory, 64)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("frames", [[-1], [True], [1.5], ["2"]])
def test_batch_rejects_inexact_frame_numbers_before_decode(
    tmp_path, monkeypatch, frames
):
    monkeypatch.setattr(
        watch.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("unexpected decoder"),
    )
    with pytest.raises(VisionReviewError):
        watch._prefetch_exact_frames(
            tmp_path / "source.mkv", frames, tmp_path / "frames", 64
        )


def _blocked_decoder(monkeypatch):
    released = threading.Event()

    class Reader(io.BytesIO):
        def read(self, size=-1):
            if not released.wait(timeout=2):
                raise AssertionError("decoder watchdog did not release blocked read")
            return b""

    class Decoder:
        stdout = Reader()
        killed = 0
        waits = []

        def poll(self):
            return -9 if released.is_set() else None

        def wait(self, timeout=None):
            self.waits.append(timeout)
            assert released.is_set(), "blocked decoder was not terminated"
            return -9

        def kill(self):
            self.killed += 1
            released.set()

    process = Decoder()
    monkeypatch.setattr(watch.subprocess, "Popen", lambda *args, **kwargs: process)
    return process


def test_batch_deadline_unblocks_read_and_reaps_owned_decoder(tmp_path, monkeypatch):
    process = _blocked_decoder(monkeypatch)
    start = time.monotonic()
    with pytest.raises(VisionReviewError, match="timed out"):
        watch._decode_frame_batch([], [0], tmp_path, 64, timeout_seconds=0.03)
    assert time.monotonic() - start < 1.5
    assert process.killed == 1
    assert process.stdout.closed
    assert process.waits == [5]


def test_batch_cancellation_unblocks_read_and_reaps_owned_decoder(
    tmp_path, monkeypatch
):
    process = _blocked_decoder(monkeypatch)
    cancellation = threading.Event()
    trigger = threading.Timer(0.02, cancellation.set)
    trigger.start()
    try:
        with pytest.raises(VisionReviewError, match="cancelled"):
            watch._decode_frame_batch(
                [], [0], tmp_path, 64, timeout_seconds=2, cancel_event=cancellation
            )
    finally:
        trigger.cancel()
        trigger.join(timeout=1)
    assert process.killed == 1
    assert process.stdout.closed
    assert process.waits == [5]


def test_batch_interrupt_reaps_owned_decoder_without_swallowing_interrupt(
    tmp_path, monkeypatch
):
    process = _blocked_decoder(monkeypatch)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(watch, "_consume_frame_batch", interrupt)
    with pytest.raises(KeyboardInterrupt):
        watch._decode_frame_batch([], [0], tmp_path, 64)
    assert process.killed == 1
    assert process.stdout.closed
    assert process.waits == [5]


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_batch_requires_finite_positive_deadline_before_spawning(
    tmp_path, monkeypatch, timeout
):
    monkeypatch.setattr(
        watch.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("unexpected decoder"),
    )
    with pytest.raises(VisionReviewError, match="deadline"):
        watch._decode_frame_batch([], [0], tmp_path, 64, timeout_seconds=timeout)


def test_already_cancelled_batch_does_not_spawn(tmp_path, monkeypatch):
    cancellation = threading.Event()
    cancellation.set()
    monkeypatch.setattr(
        watch.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("unexpected decoder"),
    )
    with pytest.raises(VisionReviewError, match="cancelled"):
        watch._decode_frame_batch([], [0], tmp_path, 64, cancel_event=cancellation)


def test_batch_deadline_reaps_actual_owned_child(tmp_path, monkeypatch):
    original_popen = subprocess.Popen
    children = []

    def track(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(watch.subprocess, "Popen", track)
    with pytest.raises(VisionReviewError, match="timed out"):
        watch._decode_frame_batch(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            [0],
            tmp_path,
            64,
            timeout_seconds=0.1,
        )
    assert len(children) == 1
    assert children[0].poll() is not None
    assert children[0].stdout.closed


@pytest.mark.parametrize("damage", ["deleted", "empty", "changed", "oversize"])
def test_review_cache_change_blocks_without_decoding_or_replacing(
    tmp_path, monkeypatch, damage
):
    path = tmp_path / "frame-000000003.png"
    png = _png()
    path.write_bytes(png)
    digest = hashlib.sha256(png).hexdigest()
    limit = 1024
    if damage == "deleted":
        path.unlink()
    elif damage == "empty":
        path.write_bytes(b"")
    elif damage == "changed":
        path.write_bytes(png + b"changed")
    else:
        path.write_bytes(b"x" * (limit + 1))
    before = path.read_bytes() if path.exists() else None
    monkeypatch.setattr(
        watch.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("unexpected decoder"),
    )
    assert watch._cached_review_frames([3], tmp_path, {3: digest}, max_bytes=limit) == (
        [],
        [3],
        [],
    )
    assert (path.read_bytes() if path.exists() else None) == before


def test_review_cache_uses_only_verified_prefetched_frames(tmp_path, monkeypatch):
    path = tmp_path / "frame-000000003.png"
    path.write_bytes(_png())
    digest = hashlib.sha256(_png()).hexdigest()
    before = path.read_bytes(), path.stat().st_mtime_ns
    monkeypatch.setattr(
        watch.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("unexpected decoder"),
    )
    assert watch._cached_review_frames([3], tmp_path, {3: digest}) == ([3], [], [path])
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
