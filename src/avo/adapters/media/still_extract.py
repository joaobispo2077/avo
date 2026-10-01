"""Exact decoded-frame selection and deterministic PNG extraction."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any

from avo.timeline.contracts import file_fingerprint
from avo.timeline.stills import StillExtractionError


def _fraction(value: str | None, *, default: Fraction | None = None) -> Fraction:
    try:
        text = str(value).replace(":", "/")
        numerator, denominator = text.split("/", 1)
        result = Fraction(int(numerator), int(denominator))
    except (AttributeError, ValueError, ZeroDivisionError):
        if default is None:
            raise StillExtractionError(f"invalid rational metadata: {value}")
        return default
    return result


def _pts(frame: dict[str, Any]) -> int | None:
    value = frame.get("best_effort_timestamp")
    if value in (None, "N/A"):
        value = frame.get("pkt_pts")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _rate(stream: dict[str, Any]) -> Fraction | None:
    value = _fraction(stream.get("avg_frame_rate"), default=Fraction(0, 1))
    return value if value > 0 else None


def _explicit_frame(
    probe: dict[str, Any], frames: list[dict[str, Any]], index: int
) -> dict[str, Any]:
    if index < 0 or index >= len(frames):
        raise StillExtractionError(f"decoded frame index is out of range: {index}")
    stream = probe["stream"]
    points = [_pts(frame) for frame in frames]
    point = points[index]
    if point is None:
        original = -1
        normalized = index
        duration = 1
        next_point = normalized + duration
    else:
        start = next((value for value in points if value is not None), point)
        original = point
        normalized = max(0, point - start)
        next_value = points[index + 1] if index + 1 < len(points) else None
        duration = int(frames[index].get("pkt_duration") or 0)
        if next_value is not None and next_value > point:
            duration = next_value - point
        duration = max(1, duration)
        next_point = normalized + duration
    rate = _rate(stream)
    return {
        "streamTimebase": _rational_payload(
            _fraction(stream.get("time_base"), default=Fraction(1, 1))
        ),
        "originalPts": original,
        "normalizedPts": normalized,
        "nextPts": next_point,
        "displayDuration": duration,
        "decodedFrameIndex": index,
        "cfrFrameRate": _rational_payload(rate) if rate else None,
        "selectionMethod": "decoded-frame-index",
        "boundaryDecision": "not-boundary",
    }


def _rational_payload(value: Fraction) -> dict[str, int]:
    return {"num": value.numerator, "den": value.denominator}


def select_frame(
    probe: dict[str, Any],
    requested_time: Fraction | None,
    *,
    decoded_frame_index: int | None = None,
) -> dict[str, Any]:
    """Resolve normalized seconds to the decoded interval ``[PTS,nextPTS)``."""
    frames = list(probe.get("frames") or [])
    if not frames:
        raise StillExtractionError("video probe returned no decoded frames")
    if decoded_frame_index is not None:
        return _explicit_frame(probe, frames, decoded_frame_index)
    if requested_time is None or requested_time < 0:
        raise StillExtractionError("non-negative requested time is required")
    points = [_pts(frame) for frame in frames]
    if any(value is None for value in points) or any(
        right <= left for left, right in pairwise(points)
    ):
        raise StillExtractionError(
            "missing, duplicate, or non-monotonic PTS requires decoded frame index"
        )
    exact_points = [int(value) for value in points if value is not None]
    start = exact_points[0]
    normalized = [value - start for value in exact_points]
    timebase = _fraction(
        (probe.get("stream") or {}).get("time_base"), default=Fraction(1, 1)
    )
    target = requested_time / timebase
    selected = None
    for index, point in enumerate(normalized):
        next_point = normalized[index + 1] if index + 1 < len(normalized) else None
        duration = int(frames[index].get("pkt_duration") or 0)
        if next_point is None:
            next_point = point + max(1, duration)
        if Fraction(point, 1) <= target < Fraction(next_point, 1):
            selected = index
            break
    if selected is None:
        raise StillExtractionError("requested time is outside decoded frame intervals")
    rate = _rate(probe["stream"])
    deltas = [right - left for left, right in pairwise(exact_points)]
    cfr = bool(rate and (not deltas or len(set(deltas)) == 1))
    original = exact_points[selected]
    next_original = (
        exact_points[selected + 1]
        if selected + 1 < len(exact_points)
        else original + max(1, int(frames[selected].get("pkt_duration") or 0))
    )
    return {
        "streamTimebase": _rational_payload(timebase),
        "originalPts": original,
        "normalizedPts": normalized[selected],
        "nextPts": normalized[selected] + (next_original - original),
        "displayDuration": next_original - original,
        "decodedFrameIndex": selected,
        "cfrFrameRate": _rational_payload(rate) if cfr and rate else None,
        "selectionMethod": "cfr-frame-map" if cfr else "pts-interval",
        "boundaryDecision": (
            "incoming"
            if selected > 0 and target == normalized[selected]
            else "not-boundary"
        ),
    }


def _rotation(stream: dict[str, Any]) -> int:
    values = [item.get("rotation") for item in stream.get("side_data_list") or []]
    values.append((stream.get("tags") or {}).get("rotate"))
    for value in values:
        try:
            return round(float(value)) % 360
        except (TypeError, ValueError):
            continue
    return 0


def media_metadata(
    probe: dict[str, Any], *, color_policy: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    stream = probe["stream"]
    width, height = int(stream["width"]), int(stream["height"])
    sar = _fraction(stream.get("sample_aspect_ratio"), default=Fraction(1, 1))
    display_width = round(width * sar)
    display_height = height
    rotation = _rotation(stream)
    if rotation in {90, 270}:
        display_width, display_height = display_height, display_width
    transfer = str(stream.get("color_transfer") or "unknown")
    hdr = transfer.lower() in {"smpte2084", "arib-std-b67", "pq", "hlg"}
    if hdr and color_policy is None:
        raise StillExtractionError("HDR extraction requires an explicit color policy")
    supported = {"hdr-preserve-v1", "hdr-tone-map-hable-v1"}
    if hdr and color_policy not in supported:
        raise StillExtractionError(f"unsupported HDR color policy: {color_policy}")
    policy_id = color_policy or "sdr-srgb-v1"
    hdr_state = (
        "hdr-tone-mapped"
        if policy_id == "hdr-tone-map-hable-v1"
        else "hdr-preserved"
        if hdr
        else "sdr"
    )
    media = {
        "encodedWidth": width,
        "encodedHeight": height,
        "displayWidth": display_width,
        "displayHeight": display_height,
        "pixelFormat": str(stream.get("pix_fmt") or "unknown"),
        "rotationDegrees": rotation,
        "sampleAspectRatio": _rational_payload(sar),
        "colorPrimaries": str(stream.get("color_primaries") or "unknown"),
        "transfer": transfer,
        "matrix": str(stream.get("color_space") or "unknown"),
        "range": {"pc": "full", "tv": "limited"}.get(
            str(stream.get("color_range") or ""), "unknown"
        ),
        "hdrState": hdr_state,
    }
    policy = {
        "policyId": policy_id,
        "version": "1.0.0",
        "conversionParameters": {
            "target": "srgb-png" if hdr_state != "hdr-preserved" else "rgb48-png",
            "rotationDegrees": rotation,
            "sampleAspectRatio": _rational_payload(sar),
        },
        "tool": {"name": "ffmpeg", "version": "system"},
    }
    return media, policy


class StillExtractAdapter:
    @staticmethod
    def select_frame(
        probe: dict[str, Any],
        requested_time: Fraction | None,
        *,
        decoded_frame_index: int | None = None,
    ) -> dict[str, Any]:
        return select_frame(
            probe, requested_time, decoded_frame_index=decoded_frame_index
        )

    def __init__(self, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def _ffmpeg_version(self) -> str:
        try:
            result = subprocess.run(
                [self.ffmpeg, "-version"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise StillExtractionError(
                "cannot identify the FFmpeg extraction tool"
            ) from exc
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        return first_line.strip() or "unknown"

    def probe(self, path: Path) -> dict[str, Any]:
        result = subprocess.run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-show_frames",
                "-show_entries",
                "stream=time_base,start_pts,width,height,pix_fmt,sample_aspect_ratio,avg_frame_rate,r_frame_rate,color_primaries,color_transfer,color_space,color_range:stream_tags=rotate:stream_side_data=rotation:frame=best_effort_timestamp,pkt_pts,pkt_duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        streams = payload.get("streams") or []
        if not streams:
            raise StillExtractionError(f"no video stream: {path}")
        return {"stream": streams[0], "frames": payload.get("frames") or []}

    def extract(
        self,
        input_path: Path,
        output_path: Path,
        *,
        requested_time: Fraction | None,
        decoded_frame_index: int | None = None,
        color_policy: str | None = None,
        width: int | None = None,
    ) -> dict[str, Any]:
        probe = self.probe(input_path)
        resolved = select_frame(
            probe,
            requested_time,
            decoded_frame_index=decoded_frame_index,
        )
        media, policy = media_metadata(probe, color_policy=color_policy)
        policy["tool"]["version"] = self._ffmpeg_version()
        if width is not None:
            policy["conversionParameters"]["outputWidth"] = width
        filters = [f"select=eq(n\\,{resolved['decodedFrameIndex']})"]
        if media["sampleAspectRatio"] != {"num": 1, "den": 1}:
            filters.extend(["scale=trunc(iw*sar):ih", "setsar=1"])
        rotation = media["rotationDegrees"]
        if rotation == 90:
            filters.append("transpose=clock")
        elif rotation == 180:
            filters.extend(["hflip", "vflip"])
        elif rotation == 270:
            filters.append("transpose=cclock")
        if policy["policyId"] == "hdr-tone-map-hable-v1":
            filters.extend(
                [
                    "zscale=t=linear:npl=100",
                    "tonemap=hable",
                    "zscale=t=bt709:m=bt709:r=pc",
                ]
            )
        filters.append(
            "format=rgb48le" if media["hdrState"] == "hdr-preserved" else "format=rgb24"
        )
        if width is not None:
            if width < 1:
                raise StillExtractionError("still width must be positive")
            filters.append(f"scale={width}:-2")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
            "-noautorotate",
            "-i",
            str(input_path),
            "-vf",
            ",".join(filters),
            "-frames:v",
            "1",
            "-fps_mode",
            "vfr",
            "-map_metadata",
            "-1",
        ]
        if media["hdrState"] != "hdr-preserved":
            command.extend(
                [
                    "-color_primaries",
                    "bt709",
                    "-color_trc",
                    "iec61966-2-1",
                    "-colorspace",
                    "bt709",
                    "-color_range",
                    "pc",
                ]
            )
        command.append(str(output_path))
        try:
            subprocess.run(command, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            raise StillExtractionError(
                f"ffmpeg still extraction failed: {exc.stderr.decode(errors='replace')}"
            ) from exc
        if not output_path.is_file():
            raise StillExtractionError("ffmpeg did not create the requested still")
        return {
            "resolvedFrame": resolved,
            "media": media,
            "colorPolicy": policy,
            "output": file_fingerprint(output_path),
        }
