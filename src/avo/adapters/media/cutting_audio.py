"""Explicit original-dialogue routing and source-clock PCM derivatives."""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from fractions import Fraction
from math import ceil
from pathlib import Path

import numpy as np

from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.cutting_contracts import validate_source_range
from avo.timeline.ports import ToolError
from avo.transcribe import source_fingerprint

_SOURCE_OBSERVATIONS: ContextVar[dict | None] = ContextVar(
    "cutting_source_observations", default=None
)
_NATIVE_PCM_OBSERVATIONS: ContextVar[dict | None] = ContextVar(
    "cutting_native_pcm_observations", default=None
)


@contextmanager
def _source_fingerprint_batch():
    if _SOURCE_OBSERVATIONS.get() is not None:
        yield
        return
    observations = {}
    token = _SOURCE_OBSERVATIONS.set(observations)
    pcm_token = _NATIVE_PCM_OBSERVATIONS.set({})
    try:
        yield
        for path, observed in observations.items():
            if source_fingerprint(path)["sha256"] != observed["sha256"]:
                raise ToolError(
                    "cutting-source-fingerprint",
                    f"source changed during verification: {path}",
                )
    finally:
        _NATIVE_PCM_OBSERVATIONS.reset(pcm_token)
        _SOURCE_OBSERVATIONS.reset(token)


def _observed_source_fingerprint(path, *, observe=None):
    observe = observe or source_fingerprint
    observations = _SOURCE_OBSERVATIONS.get()
    if observations is None:
        return observe(path)
    resolved = Path(path).resolve()
    if resolved not in observations:
        observations[resolved] = observe(resolved)
    return dict(observations[resolved])


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


def _execute(command, *, timeout=120):
    try:
        result = subprocess.run(
            command, capture_output=True, check=True, timeout=timeout
        )
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


def _native_source_pcm(path, bindings, channels, rate, output_dir):
    """Decode originals once per batch; seek PCM without container PTS rounding."""
    key = content_hash(
        {
            k: bindings[k]
            for k in ("sourceFingerprint", "selection", "syncRef", "decoder")
        }
    )
    cache = _NATIVE_PCM_OBSERVATIONS.get()
    cached = cache.get(key) if cache is not None else None
    if cached is None:
        stem = Path(output_dir) / ("source-" + key + ".wav")
        stem.parent.mkdir(parents=True, exist_ok=True)
        pan = "|".join(f"c{i}=c{channel}" for i, channel in enumerate(channels))
        timeout = min(7200, max(120, ceil(path.stat().st_size / (16 * 1024**2)) + 120))
        _execute(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(path),
                "-map",
                f"0:{bindings['selection']['streamIndex']}",
                "-af",
                f"pan={len(channels)}c|{pan}",
                "-ar",
                str(rate),
                "-c:a",
                "pcm_s32le",
                "-rf64",
                "auto",
                str(stem),
            ],
            timeout=timeout,
        )
        cached = file_fingerprint(stem)
        _observed_source_fingerprint(stem, observe=lambda _: cached)
        if cache is not None:
            cache[key] = cached
    if file_fingerprint(Path(cached["locator"])) != cached:
        raise ToolError("cutting-source-fingerprint", "native source PCM changed")
    return dict(cached)


def _extraction_input(
    path, stream_index, channels, rate, bindings, output_dir, first, native_seek
):
    if not native_seek:
        return path, stream_index, channels, first, []
    stem = _native_source_pcm(path, bindings, channels, rate, output_dir)
    bindings["nativeOriginalPcm"] = stem
    return (
        Path(stem["locator"]),
        0,
        list(range(len(channels))),
        0,
        ["-ss", str(first / rate)],
    )


def extract_dialogue_pcm(
    source,
    *,
    selection,
    source_range,
    fingerprint,
    sync_ref,
    output_dir,
    native_render_seek=False,
):
    if type(native_render_seek) is not bool:
        raise ToolError("cutting-audio-routing", "native render seek must be boolean")
    path = Path(source["locator"] if isinstance(source, dict) else source)
    actual = _observed_source_fingerprint(path)
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
        "preprocessing": "native-s32/analysis-mono-s16-16k-v1"
        + ("/native-source-pcm-seek-v1" if native_render_seek else ""),
    }
    input_path, stream_index, routed_channels, offset, seek = _extraction_input(
        path,
        stream["index"],
        channels,
        rate,
        bindings,
        output_dir,
        start_sample,
        native_render_seek,
    )
    destination = Path(output_dir) / content_hash(bindings)
    destination.mkdir(parents=True, exist_ok=True)
    native, analysis = destination / "native.wav", destination / "analysis.wav"
    pan = "|".join(
        f"c{index}=c{channel}" for index, channel in enumerate(routed_channels)
    )
    filters = f"atrim=start_sample={offset}:end_sample={offset + end_sample - start_sample},asetpts=PTS-STARTPTS,pan={len(channels)}c|{pan}"
    _execute(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            *seek,
            "-i",
            str(input_path),
            "-map",
            f"0:{stream_index}",
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
