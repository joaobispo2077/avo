"""ffprobe-backed raw inventory and file identity."""

from __future__ import annotations

import json
import re
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Any

from avo.timeline.contracts import file_fingerprint, fingerprint_stage

from .local_source import local_source_arguments
from .still_probe import _SUFFIXES

INVENTORY_ENTRIES = (
    "format=duration:stream=index,codec_name,codec_type,width,height,time_base,"
    "r_frame_rate,avg_frame_rate,duration_ts,duration,start_pts,start_time,"
    "sample_rate,channels,channel_layout,sample_aspect_ratio,nb_frames:stream_tags=DURATION"
)


def _number_or_none(value, convert):
    try:
        return convert(value)
    except (TypeError, ValueError):
        return None


def _stream_duration(stream):
    duration = _number_or_none(stream.get("duration"), float)
    if duration is not None:
        return duration
    tags = stream.get("tags")
    if not isinstance(tags, dict):
        return None
    value = tags.get("DURATION")
    if not isinstance(value, str) or len(value) > 18:
        return None
    match = re.fullmatch(r"([0-9]{2}):([0-5][0-9]):([0-5][0-9]\.[0-9]{1,9})", value)
    if match is None:
        return None
    hours, minutes, seconds = map(Decimal, match.groups())
    return float(hours * 3600 + minutes * 60 + seconds)


def _video_stream(stream):
    return {
        "index": int(stream.get("index", 0)),
        "codec": stream.get("codec_name"),
        "codecName": stream.get("codec_name"),
        "frameCount": _number_or_none(stream.get("nb_frames"), int),
        "sampleAspectRatio": stream.get("sample_aspect_ratio"),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "timeBase": str(stream.get("time_base") or ""),
        "frameRate": str(stream.get("r_frame_rate") or ""),
        "averageFrameRate": str(stream.get("avg_frame_rate") or ""),
        "durationTicks": _number_or_none(stream.get("duration_ts"), int),
        "durationSeconds": _stream_duration(stream),
        "startTicks": _number_or_none(stream.get("start_pts"), int),
        "startTimeSeconds": _number_or_none(stream.get("start_time"), float),
    }


def _audio_stream(stream):
    return {
        "index": int(stream.get("index", 0)),
        "codec": stream.get("codec_name"),
        "sampleRate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "channelLayout": str(stream.get("channel_layout") or ""),
        "timeBase": str(stream.get("time_base") or ""),
        "durationTicks": _number_or_none(stream.get("duration_ts"), int),
        "durationSeconds": _stream_duration(stream),
        "startTicks": _number_or_none(stream.get("start_pts"), int),
        "startTimeSeconds": _number_or_none(stream.get("start_time"), float),
    }


class FfprobeMediaAdapter:
    """Inventory muxed sources and expose hash, streams, clocks, and sync risk."""

    def fingerprint(self, path: Path) -> dict[str, Any]:
        return file_fingerprint(Path(path))

    def verify_video_clock(
        self,
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
        from .video_clock import verify_video_clock

        return verify_video_clock(
            path,
            stream_index,
            frame_rate,
            time_base=time_base,
            expected_sha256=expected_sha256,
            expected_frames=expected_frames,
            start_ticks=start_ticks,
            cache=cache,
        )

    def inventory(self, paths: list[Path]) -> dict[str, Any]:
        sources = [self._describe(Path(path)) for path in paths]
        clocks = {
            (
                source["durationSeconds"],
                source["streams"]["video"][0]["timeBase"]
                if source["streams"]["video"]
                else "",
                source["streams"]["audio"][0]["sampleRate"]
                if source["streams"]["audio"]
                else 0,
            )
            for source in sources
        }
        if len(sources) <= 1:
            sync_risk = {
                "status": "not-applicable",
                "reasons": ["single-muxed-clock"],
                "assessed": True,
            }
        elif len(clocks) > 1:
            sync_risk = {
                "status": "risk-detected",
                "reasons": ["multiple-source-clocks"],
                "assessed": True,
            }
        else:
            sync_risk = {
                "status": "not-applicable",
                "reasons": ["shared-muxed-clock"],
                "assessed": True,
            }
        return {"sources": sources, "syncRisk": sync_risk}

    def _describe(self, path: Path) -> dict[str, Any]:
        input_arguments = local_source_arguments(
            path, literal_still=path.suffix.lower() in _SUFFIXES
        )
        with fingerprint_stage(verify_on_exit=True):
            fingerprint = file_fingerprint(path)
            return self._describe_locked(path, fingerprint, input_arguments)

    def _describe_locked(self, path, fingerprint, input_arguments):
        probe = json.loads(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    *input_arguments,
                    "-show_entries",
                    INVENTORY_ENTRIES,
                    "-of",
                    "json",
                    "-i",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout
        )
        video: list[dict[str, Any]] = []
        audio: list[dict[str, Any]] = []
        for stream in probe.get("streams") or []:
            codec = stream.get("codec_type")
            if codec == "video":
                video.append(_video_stream(stream))
            elif codec == "audio":
                audio.append(_audio_stream(stream))
        duration = float((probe.get("format") or {}).get("duration") or 0)
        return {
            "sourceId": path.stem,
            "locator": str(path),
            "fingerprint": fingerprint,
            "durationSeconds": duration,
            "streams": {"video": video, "audio": audio},
        }


def media_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def library_metadata(path: Path) -> dict[str, Any]:
    """Probe library metadata without hashing footage or invoking inference."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    value = json.loads(result.stdout)
    duration = (value.get("format") or {}).get("duration")
    return {
        "durationSeconds": float(duration) if duration is not None else None,
        "audio": any(
            item.get("codec_type") == "audio" for item in value.get("streams", [])
        ),
    }


def audio_sample_rate(selection: dict, locator: Path) -> int:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(locator)],
        capture_output=True,
        text=True,
        check=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    stream = next(item for item in streams if item["index"] == selection["streamIndex"])
    if stream["codec_type"] != "audio":
        raise ValueError("canonical selected stream must contain audio")
    return int(stream["sample_rate"])
