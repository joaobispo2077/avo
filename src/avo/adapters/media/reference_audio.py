"""Measure energy candidates on an explicitly selected original audio clock."""

import re
import subprocess
import sys
from array import array
from bisect import bisect_right
from fractions import Fraction
from math import ceil, isfinite

from .local_source import local_source_arguments
from .waveform import find_transient_onsets

_MAX_SAMPLES = 30 * 96_000
_FRAME = re.compile(
    r"ashowinfo[^\n]*\bpts:(-?\d+)\b[^\n]*\brate:(\d+)\s+nb_samples:(\d+)"
)


def _audio_command(source, destination, stream, selection, bounds):
    index = selection["streamIndex"]
    channel = selection["channelIndex"]
    rate = int(stream["sample_rate"])
    start, end = bounds
    seek = start // rate - 2
    origin = _stream_origin(stream) or 0
    seek_args = (
        ["-seek_timestamp", "1", "-ss", str(seek)] if seek > max(0, origin) else []
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-nostdin",
        "-n",
        "-copyts",
        *local_source_arguments(source),
        *seek_args,
        "-i",
        str(source),
        "-map",
        f"0:{index}",
        "-vn",
        "-sn",
        "-dn",
        "-filter_threads",
        "1",
        "-af",
        f"asettb=1/{rate},atrim=start_pts={start}:end_pts={end},pan=mono|c0=c{channel},ashowinfo",
        "-fs",
        str((_MAX_SAMPLES + 1) * 4),
        "-c:a",
        "pcm_f32le",
        "-f",
        "f32le",
        str(destination),
    ]


def _stream_origin(stream):
    start = stream.get("start_pts")
    if start in (None, "N/A"):
        return None
    return int(start) * Fraction(stream["time_base"])


def _packet_clock(log, rate, bounds, tolerance):
    offsets, points = [], []
    offset = 0
    start, end = bounds
    for pts, packet_rate, length in _FRAME.findall(log):
        pts, packet_rate, length = int(pts), int(packet_rate), int(length)
        if packet_rate != rate or not start <= pts < pts + length <= end:
            raise ValueError("Audio samples escape the selected stream clock or range")
        if points and abs(pts - (points[0] + offset)) > tolerance:
            raise ValueError("Selected audio contains a discontinuous sample clock")
        points.append(pts)
        offsets.append(offset)
        offset += length
    if not 0 < offset <= _MAX_SAMPLES:
        raise ValueError("Selected audio has no bounded decoded coverage")
    return offsets, points, offset


def _pcm(destination, size):
    if destination.stat().st_size != size * 4:
        raise ValueError("Selected audio PCM bytes disagree with observed timing")
    samples = array("f")
    samples.frombytes(destination.read_bytes())
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) != size or not all(map(isfinite, samples)):
        raise ValueError("Selected audio contains unsupported PCM samples")
    return samples


def measure_reference_audio(source, destination, scope, selection, stream, decode_log):
    """Return bounded sample-clock timing, or an explicit reason to abstain."""
    if stream.get("codec_type") != "audio":
        raise ValueError("Reference timing requires one exact original audio stream")
    rate = int(stream["sample_rate"])
    if not 8_000 <= rate <= 96_000 or selection["channelIndex"] >= stream["channels"]:
        raise ValueError("Reference timing requires a valid channel at 8–96 kHz")
    base = Fraction(scope["timebase"]["num"], scope["timebase"]["den"])
    bounds = tuple(ceil(scope[key] * base * rate) for key in ("startTicks", "endTicks"))
    precision = max(1, ceil(Fraction(stream["time_base"]) * rate))
    try:
        command = _audio_command(source, destination, stream, selection, bounds)
        offsets, points, size = _packet_clock(
            decode_log(command), rate, bounds, precision
        )
        samples = _pcm(destination, size)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {
            "status": "unavailable",
            "selection": selection,
            "reason": "unverified-audio-clock",
        }
    window, hop = max(1, rate // 100), max(1, rate // 200)
    detected = find_transient_onsets(
        [samples],
        0,
        size,
        threshold=selection["energyThreshold"],
        window_samples=window,
        hop_samples=hop,
        dc_removal=True,
    )
    onsets = []
    for index in detected[:128]:
        packet = bisect_right(offsets, index) - 1
        onsets.append(points[packet] + index - offsets[packet])
    result = {
        "status": "observed",
        "selection": selection,
        "sampleRate": rate,
        "startSample": points[0],
        "endSampleExclusive": points[-1] + size - offsets[-1],
        "windowSamples": window,
        "hopSamples": hop,
        "clockUncertaintySamples": precision,
        "onsetSamples": onsets,
        "truncated": len(detected) > len(onsets),
    }
    origin = _stream_origin(stream)
    if origin is not None:
        result["streamOriginSample"] = round(origin * rate)
    return result
