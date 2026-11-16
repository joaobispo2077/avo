"""Bounded native-channel SFX facts; peaks are candidates, not perceptual approval."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from avo.adapters.media.local_source import local_source_arguments
from avo.adapters.media.waveform import _onset_clusters
from avo.timeline.contracts import file_fingerprint


@lru_cache(maxsize=8)
def _binary_digest(path, size, modified):
    return file_fingerprint(Path(path))["sha256"]


def _binary(name):
    path = shutil.which(name)
    if not path:
        raise ValueError(f"{name} is required for explicitly requested sound analysis")
    info = Path(path).stat()
    return path, _binary_digest(path, info.st_size, info.st_mtime_ns)


def _execute(command, output, errors):
    with output.open("wb") as stdout, errors.open("wb") as stderr:
        try:
            result = subprocess.run(
                command, stdout=stdout, stderr=stderr, timeout=45, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"sound decoder unavailable: {exc}") from exc
    if result.returncode:
        with errors.open("rb") as stream:
            detail = stream.read(2048).decode("utf-8", errors="replace")
        raise ValueError(f"sound decoder failed: {detail}")


def _probe(binary, path, directory):
    output, errors = directory / "probe.json", directory / "probe-errors.txt"
    _execute(
        [
            binary,
            "-v",
            "error",
            *local_source_arguments(path),
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels,duration_ts,time_base,duration:format=duration",
            "-of",
            "json",
            str(path),
        ],
        output,
        errors,
    )
    with output.open("rb") as stream:
        data = stream.read(16385)
    if len(data) > 16384:
        raise ValueError("sound probe exceeds metadata budget")
    parsed = json.loads(data)
    streams = parsed.get("streams") or []
    if len(streams) != 1:
        raise ValueError("one selected native audio stream is required")
    stream = streams[0]
    rate, channels = int(stream["sample_rate"]), int(stream["channels"])
    if not 1 <= rate <= 192000 or not 1 <= channels <= 8:
        raise ValueError(
            "native sound rate/channels exceed the bounded decoder support"
        )
    samples, duration = _duration(stream, parsed.get("format") or {}, rate)
    return rate, channels, samples, duration


def _duration(stream, format_info, rate):
    try:
        exact = int(stream["duration_ts"]) * Fraction(stream["time_base"]) * rate
        samples = int(exact) if exact.denominator == 1 and exact >= 0 else None
    except (KeyError, ValueError, ZeroDivisionError):
        samples = None
    try:
        duration = float(stream.get("duration") or format_info.get("duration"))
        if not math.isfinite(duration) or duration < 0:
            duration = None
    except (TypeError, ValueError):
        duration = None
    return samples, duration


class SfxAnalyzer:
    """Decode at native rate/channel order with explicit memory/time coverage."""

    def __init__(self, *, max_seconds=30, max_decoded_bytes=16 * 1024 * 1024):
        if (
            isinstance(max_seconds, bool)
            or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds)
            or not 0 < max_seconds <= 300
        ):
            raise ValueError("sound analysis duration must be in (0, 300] seconds")
        if (
            type(max_decoded_bytes) is not int
            or not 4096 <= max_decoded_bytes <= 64 * 1024 * 1024
        ):
            raise ValueError("sound decoded-byte budget must be 4096..67108864")
        self.max_seconds = max_seconds
        self.max_decoded_bytes = max_decoded_bytes

    @property
    def identity(self):
        _, ffmpeg_sha = _binary("ffmpeg")
        _, ffprobe_sha = _binary("ffprobe")
        return {
            "id": "avo-sfx-facts",
            "version": "1",
            "maxSeconds": self.max_seconds,
            "decoder": f"ffmpeg:{ffmpeg_sha};ffprobe:{ffprobe_sha}",
            "maxDecodedBytes": self.max_decoded_bytes,
            "channelPolicy": "sum-squared",
            "thresholdRatio": 0.001,
            "spectralWindowSamples": 4096,
        }

    def __call__(self, path, *, source_sha256):
        local_source_arguments(path)
        ffmpeg, _ = _binary("ffmpeg")
        ffprobe, _ = _binary("ffprobe")
        with TemporaryDirectory(prefix="avo-sfx-") as temporary:
            directory = Path(temporary)
            rate, channels, total, duration = _probe(ffprobe, path, directory)
            maximum = min(
                int(self.max_seconds * rate), self.max_decoded_bytes // (4 * channels)
            )
            if maximum < 1:
                raise ValueError("sound decode budget cannot contain one native sample")
            decoded, raw_count = _decode(
                ffmpeg, path, directory, rate, channels, maximum
            )
        complete = raw_count <= maximum and (total is None or total == raw_count)
        if total is None and complete:
            total = raw_count
            duration = total / rate
        return {
            "sourceSha256": source_sha256,
            "analyzer": self.identity,
            "sampleRate": rate,
            "channels": channels,
            "sourceSamples": total,
            "analyzedSamples": len(decoded),
            "coverage": "complete" if complete else "partial",
            "durationSeconds": duration,
            **_facts(decoded, rate),
        }


def _decode(binary, path, directory, rate, channels, maximum):
    output, log = directory / "decoded.f32", directory / "decode-output.txt"
    errors = directory / "decode-errors.txt"
    _execute(
        [
            binary,
            "-nostdin",
            "-v",
            "error",
            *local_source_arguments(path),
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-c:a",
            "pcm_f32le",
            "-f",
            "f32le",
            "-t",
            f"{(maximum + 1) / rate:.12f}",
            "-fs",
            str((maximum + 2) * channels * 4),
            "-y",
            str(output),
        ],
        log,
        errors,
    )
    with output.open("rb") as stream:
        payload = stream.read((maximum + 2) * channels * 4 + 1)
    if not payload or len(payload) % (channels * 4):
        raise ValueError("sound decoder returned empty or incomplete native PCM frames")
    raw = np.frombuffer(payload, dtype="<f4").reshape(-1, channels)
    samples = raw[:maximum].astype(np.float64)
    if not np.isfinite(samples).all():
        raise ValueError("sound decoder returned nonfinite PCM samples")
    return samples, len(raw)


def _facts(samples, rate):
    energy = np.einsum("ij,ij->i", samples, samples)
    maximum = float(np.max(energy))
    threshold = max(1e-12, maximum * 0.001)
    active = np.flatnonzero(energy >= threshold)
    silent = len(active) == 0
    start, end = (int(active[0]), int(active[-1]) + 1) if not silent else (0, 0)
    peak_sample = int(np.argmax(energy))
    window = max(1, rate // 1000)
    onsets = (
        _onset_clusters(
            energy,
            0,
            len(energy),
            threshold,
            window_samples=window,
            hop_samples=window,
        )
        if not silent
        else []
    )
    return {
        "usefulRange": {"startSample": start, "endSampleExclusive": end},
        "onsets": onsets[:256],
        "onsetCount": len(onsets),
        "onsetCoverage": "partial" if len(onsets) > 256 else "complete",
        "energyPeaks": [peak_sample] if not silent else [],
        "attackSeconds": (peak_sample - start) / rate if not silent else None,
        "decaySeconds": (end - 1 - peak_sample) / rate if not silent else None,
        "rms": float(np.sqrt(np.sum(energy) / samples.size)),
        "peak": float(np.max(np.abs(samples))),
        "spectralCentroidHz": _centroid(samples, rate) if not silent else None,
        "silence": silent,
    }


def _centroid(samples, rate):
    # Phase-safe channel power; a stereo polarity inversion cannot erase sound.
    # Fixed windows keep native long/192 kHz sounds inside the declared PCM budget.
    spectrum = np.zeros(2049)
    for start in range(0, len(samples), 4096):
        window = samples[start : start + 4096]
        spectrum += np.sum(np.abs(np.fft.rfft(window, n=4096, axis=0)) ** 2, axis=1)
    total = float(np.sum(spectrum))
    return (
        float(np.dot(np.fft.rfftfreq(4096, 1 / rate), spectrum) / total)
        if total
        else None
    )
