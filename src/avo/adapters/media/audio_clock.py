"""Bounded decoded sample-count evidence for explicitly declared audio tails."""

import re
from pathlib import Path

from avo.timeline.contracts import file_fingerprint, fingerprint_stage

from .local_source import local_source_arguments
from .video_clock import MAX_LINE_BYTES, MAX_OUTPUT_BYTES, MAX_PACKETS, _scan


def _read_samples(stdout):
    samples = total = frames = 0
    while line := stdout.readline(MAX_LINE_BYTES + 1):
        frames += 1
        total += len(line)
        if (
            len(line) > MAX_LINE_BYTES
            or total > MAX_OUTPUT_BYTES
            or frames > MAX_PACKETS
        ):
            raise ValueError("Audio sample scan exceeds its record/byte limit")
        if not re.fullmatch(rb"[0-9]+\r?\n", line):
            raise ValueError("Audio sample scan contains an invalid frame count")
        count = int(line)
        if not 0 < count <= 1048576:
            raise ValueError("Audio frame sample count is outside supported bounds")
        samples += count
    if not samples:
        raise ValueError("Audio sample scan has no decoded frames")
    return samples


def verify_audio_sample_count(path, stream_index, *, expected_sha256):
    if type(stream_index) is not int or stream_index < 0:
        raise ValueError("Audio sample scan requires an absolute stream index")
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[a-f0-9]{64}", expected_sha256
    ):
        raise ValueError("Audio sample scan requires an original fingerprint")
    path = Path(path)
    with fingerprint_stage(verify_on_exit=True):
        if file_fingerprint(path)["sha256"] != expected_sha256:
            raise ValueError("Original changed before audio sample scan")
        count = _scan(
            [
                "ffprobe",
                "-v",
                "error",
                *local_source_arguments(path),
                "-select_streams",
                str(stream_index),
                "-show_frames",
                "-show_entries",
                "frame=nb_samples",
                "-of",
                "csv=p=0",
                str(path),
            ],
            read_output=_read_samples,
        )
    return {
        "status": "verified",
        "sourceSha256": expected_sha256,
        "streamIndex": stream_index,
        "sampleCount": count,
        "method": "decoded-frame-nb-samples-v1",
    }
