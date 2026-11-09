"""Fingerprint-bound whole-stream packet PTS verification without picture decode."""

from __future__ import annotations

import hashlib
import re
import subprocess
import threading
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from avo.timeline.contracts import ContractError, file_fingerprint, fingerprint_stage

from .local_source import local_source_arguments

MAX_PACKETS = 1_000_000
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 256
TIMEOUT_SECONDS = 60
_FLAGS = {b"K_", b"__", b"_D", b"KD", b"K__", b"___", b"_D_", b"KD_"}
_METHOD = "packet-pts-grid-v1"


class VideoClockError(ValueError):
    """The selected original's complete packet clock could not be verified."""


def _rational(value, label):
    try:
        if isinstance(value, dict):
            if set(value) != {"num", "den"} or any(
                type(value[key]) is not int for key in ("num", "den")
            ):
                raise ValueError("invalid rational")
            result = Fraction(value["num"], value["den"])
        elif isinstance(value, (Fraction, str)):
            result = Fraction(value)
        else:
            raise ValueError("invalid rational")
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise VideoClockError(
            f"Video clock requires an exact positive {label}"
        ) from exc
    if (
        result <= 0
        or max(result.numerator.bit_length(), result.denominator.bit_length()) > 63
    ):
        raise VideoClockError(
            f"Video clock {label} exceeds the supported rational range"
        )
    return result


def _parameters(
    stream_index, frame_rate, time_base, expected_sha256, expected_frames, start_ticks
):
    if type(stream_index) is not int or stream_index < 0:
        raise VideoClockError(
            "Video clock requires an absolute nonnegative stream index"
        )
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[a-f0-9]{64}", expected_sha256
    ):
        raise VideoClockError("Video clock requires the expected original fingerprint")
    if expected_frames is not None and (
        type(expected_frames) is not int or expected_frames <= 0
    ):
        raise VideoClockError(
            "Video clock frame count must be a positive integer or unknown"
        )
    if start_ticks is not None and type(start_ticks) is not int:
        raise VideoClockError("Video clock origin must use integral source ticks")
    return _rational(frame_rate, "frame rate"), _rational(time_base, "timebase")


def _record(line):
    if not line.endswith(b"\n"):
        raise VideoClockError("Incomplete packet timing record")
    fields = line.rstrip(b"\r\n").split(b",")
    if (
        len(fields) != 2
        or not re.fullmatch(rb"-?[0-9]+", fields[0])
        or fields[1] not in _FLAGS
    ):
        raise VideoClockError(
            "Missing or unrecognized packet PTS/flags; frame correspondence is unverified"
        )
    return int(fields[0]), b"D" in fields[1]


def _read_packets(stdout):
    packets, total = [], 0
    while line := stdout.readline(MAX_LINE_BYTES + 1):
        total += len(line)
        if len(line) > MAX_LINE_BYTES or total > MAX_OUTPUT_BYTES:
            raise VideoClockError("Packet timing output exceeds its byte/line limit")
        if line in {b"\n", b"\r\n"}:
            continue
        if len(packets) >= MAX_PACKETS:
            raise VideoClockError("Packet timing scan exceeds its packet count limit")
        packets.append(_record(line))
    return packets


def _kill(process):
    try:
        if process.poll() is None:
            process.kill()
    except OSError:
        pass


def _scan(arguments):
    try:
        process = subprocess.Popen(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as exc:
        raise VideoClockError("Video packet clock probe could not start") from exc
    timed_out = threading.Event()

    def expire():
        timed_out.set()
        _kill(process)

    timer = threading.Timer(TIMEOUT_SECONDS, expire)
    timer.daemon = True
    timer.start()
    try:
        packets = _read_packets(process.stdout)
        code = process.wait()
        if timed_out.is_set():
            raise VideoClockError(
                "Video packet clock probe timed out at its execution limit"
            )
        if code:
            raise VideoClockError(
                "Video packet clock probe failed; no timing evidence was admitted"
            )
        return packets
    finally:
        timer.cancel()
        _kill(process)
        process.stdout.close()
        process.wait()


def _header_consistency(packets, points, expected_frames, start_ticks):
    if any(discard for _, discard in packets) and (
        expected_frames is None or start_ticks is None
    ):
        raise VideoClockError(
            "Discarded video packets require consistent known header count and origin"
        )
    if expected_frames is not None and len(points) != expected_frames:
        raise VideoClockError(
            "Packet/frame correspondence differs from the source header frame count"
        )
    if start_ticks is not None and points[0] != start_ticks:
        raise VideoClockError(
            "First presented video PTS differs from the source header origin"
        )


def _presentation_points(packets, expected_frames, start_ticks):
    points = sorted(pts for pts, discard in packets if not discard)
    if not points or len(set(points)) != len(points):
        raise VideoClockError("Missing or duplicate presented packet PTS")
    _header_consistency(packets, points, expected_frames, start_ticks)
    return points


def _verify_grid(points, fps, base):
    step = 1 / (fps * base)
    if step < 1:
        raise VideoClockError(
            "Video frame period cannot be represented by at least one source tick"
        )
    origin = points[0]
    for ordinal, point in enumerate(points):
        error = abs(Fraction(point - origin) - ordinal * step)
        if error and (step.denominator == 1 or error >= 1):
            raise VideoClockError(
                "Irregular video packet PTS contradicts the exact frame grid"
            )


def _timing_hash(packets, base, fps):
    digest = hashlib.sha256(f"{_METHOD}:{base}:{fps}\n".encode("ascii"))
    for pts, discard in sorted(packets):
        digest.update(f"{pts},{int(discard)}\n".encode("ascii"))
    return digest.hexdigest()


def _evidence(
    path,
    stream_index,
    fps,
    base,
    expected_sha256,
    expected_frames,
    start_ticks,
    input_arguments,
):
    packets = _scan(
        [
            "ffprobe",
            "-v",
            "error",
            *input_arguments,
            "-select_streams",
            str(stream_index),
            "-show_packets",
            "-show_entries",
            "packet=pts,flags:packet_side_data=",
            "-of",
            "csv=p=0",
            "-i",
            str(path),
        ]
    )
    points = _presentation_points(packets, expected_frames, start_ticks)
    _verify_grid(points, fps, base)
    return {
        "status": "verified",
        "sourceSha256": expected_sha256,
        "streamIndex": stream_index,
        "frameRate": {"num": fps.numerator, "den": fps.denominator},
        "method": _METHOD,
        "packetCount": len(points),
        "timeBase": {"num": base.numerator, "den": base.denominator},
        "originTicks": points[0],
        "timingSha256": _timing_hash(packets, base, fps),
    }


def verify_video_clock(
    path,
    stream_index,
    frame_rate,
    *,
    time_base,
    expected_sha256,
    expected_frames=None,
    start_ticks=None,
    cache=None,
):
    """Verify all packet PTS; a cache hit still verifies the current original bytes."""
    input_arguments = local_source_arguments(path)
    fps, base = _parameters(
        stream_index,
        frame_rate,
        time_base,
        expected_sha256,
        expected_frames,
        start_ticks,
    )
    path = Path(path)
    key = (expected_sha256, stream_index, fps, base, expected_frames, start_ticks)
    try:
        with fingerprint_stage(verify_on_exit=True):
            actual = file_fingerprint(path)
            if actual["sha256"] != expected_sha256:
                raise VideoClockError(
                    "Original fingerprint changed before packet clock verification"
                )
            if cache is not None and key in cache:
                evidence = deepcopy(cache[key])
            else:
                evidence = _evidence(
                    path,
                    stream_index,
                    fps,
                    base,
                    expected_sha256,
                    expected_frames,
                    start_ticks,
                    input_arguments,
                )
    except (ContractError, OSError) as exc:
        raise VideoClockError(
            "Original bytes changed or became unavailable during packet clock verification"
        ) from exc
    if cache is not None:
        cache[key] = deepcopy(evidence)
    return evidence
