"""Explicit original-dialogue routing and source-clock PCM derivatives."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np

from avo.timeline.contracts import content_hash
from avo.timeline.cutting_contracts import validate_source_range
from avo.timeline.ports import ToolError
from avo.transcribe import source_fingerprint


def read_pcm(path: Path):
    try:
        from scipy.io import wavfile

        rate, audio = wavfile.read(path)
        if audio.dtype.kind != "i" or audio.dtype.itemsize not in {2, 4}:
            raise ValueError("analysis requires signed 16/32-bit PCM")
        channels = 1 if audio.ndim == 1 else audio.shape[1]
        samples = audio.reshape(-1, channels).astype(np.float32) / 2 ** (
            audio.dtype.itemsize * 8 - 1
        )
        if not len(samples) or not np.isfinite(samples).all():
            raise ValueError("decoded PCM is empty or non-finite")
        return samples, rate
    except (OSError, ValueError, EOFError) as exc:
        raise ToolError("cutting-audio-decode", str(exc)) from exc


def _execute(command):
    try:
        result = subprocess.run(command, capture_output=True, check=True, timeout=120)
        return result.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolError(
            "cutting-audio-decode", f"explicit PCM extraction failed: {exc}"
        ) from exc


def _validate_channels(channels, available):
    if not channels or len(set(channels)) != len(channels):
        raise ToolError("cutting-audio-routing", "explicit dialogue routing is invalid")
    for channel in channels:
        if (
            isinstance(channel, bool)
            or not isinstance(channel, int)
            or not 0 <= channel < available
        ):
            raise ToolError(
                "cutting-audio-routing", "explicit dialogue routing is invalid"
            )


def _verify_native(native, rate, expected, channels):
    samples, native_rate = read_pcm(native)
    if native_rate != rate or abs(len(samples) - expected) > 1:
        raise ToolError(
            "cutting-audio-decode", "source PCM does not cover requested interval"
        )
    per_channel = np.sqrt(np.mean(samples.astype(np.float64) ** 2, axis=0))
    mono = samples.mean(axis=1)
    mono_rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    if (
        len(channels) > 1
        and max(per_channel) > 1e-5
        and mono_rms < max(per_channel) * 0.1
    ):
        raise ToolError(
            "cutting-audio-routing", "unsafe dialogue channel phase cancellation"
        )


def _selected_stream(path, selection):
    probe = json.loads(
        _execute(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)])
    )
    stream = next(
        (
            item
            for item in probe["streams"]
            if item["index"] == selection.get("streamIndex")
        ),
        None,
    )
    channels = selection.get("channels")
    if stream is None or stream.get("codec_type") != "audio":
        raise ToolError("cutting-audio-routing", "explicit dialogue routing is invalid")
    _validate_channels(channels, stream["channels"])
    declared = selection.get("sourceSampleRate")
    if declared is not None and declared != int(stream["sample_rate"]):
        raise ToolError(
            "cutting-audio-routing", "declared native rate differs from source"
        )
    return stream, channels


def extract_dialogue_pcm(
    source, *, selection, source_range, fingerprint, sync_ref, output_dir
):
    path = Path(source["locator"] if isinstance(source, dict) else source)
    actual = source_fingerprint(path)
    if actual["sha256"] != fingerprint.get("sha256"):
        raise ToolError(
            "cutting-source-fingerprint", "source fingerprint differs from expected"
        )
    if not sync_ref or not sync_ref.get("sha256"):
        raise ToolError("cutting-audio-routing", "approved Sync reference is required")
    validate_source_range(source_range)
    stream, channels = _selected_stream(path, selection)
    rate = int(stream["sample_rate"])
    clock = Fraction(source_range["timebase"]["num"], source_range["timebase"]["den"])
    start = source_range["startTicks"] * clock
    end = source_range["endTicksExclusive"] * clock
    # Analysis bounds cover the requested interval rather than truncate its edges.
    first = start * rate
    last = end * rate
    start_sample = first.numerator // first.denominator
    end_sample = -(-last.numerator // last.denominator)
    bindings = {
        "sourceFingerprint": actual["sha256"],
        "selection": selection,
        "sourceRange": source_range,
        "syncRef": sync_ref,
        "decoder": _execute(["ffmpeg", "-version"]).decode("utf-8").splitlines()[0],
        "preprocessing": "native-s32/analysis-mono-s16-16k-v1",
    }
    destination = Path(output_dir) / content_hash(bindings)
    destination.mkdir(parents=True, exist_ok=True)
    native, analysis = destination / "native.wav", destination / "analysis.wav"
    pan = "|".join(f"c{index}=c{channel}" for index, channel in enumerate(channels))
    filters = f"atrim=start_sample={start_sample}:end_sample={end_sample},asetpts=PTS-STARTPTS,pan={len(channels)}c|{pan}"
    _execute(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-map",
            f"0:{stream['index']}",
            "-af",
            filters,
            "-c:a",
            "pcm_s32le",
            str(native),
        ]
    )
    _verify_native(native, rate, end_sample - start_sample, channels)
    _execute(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(native),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(analysis),
        ]
    )
    bindings["nativePcmSha256"] = source_fingerprint(native)["sha256"]
    bindings["analysisPcmSha256"] = source_fingerprint(analysis)["sha256"]
    return {
        "nativePath": str(native),
        "analysisPath": str(analysis),
        "sampleRate": rate,
        "channels": channels,
        "range": source_range,
        "sourceStart": start_sample / rate,
        "fingerprint": fingerprint,
        "bindings": bindings,
    }
