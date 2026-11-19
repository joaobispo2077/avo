"""Bounded display proxy capture for explicitly selected original video ranges."""

import json
import re
import subprocess
import tempfile
from fractions import Fraction
from io import BytesIO
from pathlib import Path

from avo.adapters.media.camera import _rotation
from avo.adapters.media.ffprobe import INVENTORY_ENTRIES
from avo.adapters.media.local_source import local_source_arguments
from avo.reference_analysis import (
    SCHEMA,
    _display_aspect,
    freeze_face_observation,
    freeze_reference_motion,
)
from avo.timeline.contracts import (
    file_fingerprint,
    fingerprint_stage,
    validate_document,
)
from avo.visual_motion_runtime import (
    detect_proxy_faces,
    measure_reference_proxy,
    preflight_face_job,
)

MAX_PROXY_BYTES = 64 * 1024 * 1024


def _source_video(path, index, options):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            *options,
            "-select_streams",
            str(index),
            "-show_entries",
            INVENTORY_ENTRIES,
            "-of",
            "json",
            "-i",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    streams = json.loads(result.stdout).get("streams") or []
    if len(streams) != 1 or streams[0].get("codec_type") != "video":
        raise ValueError("Face capture requires one exact original video stream")
    return streams[0]


def _geometry(stream):
    sar = Fraction((stream.get("sample_aspect_ratio") or "1:1").replace(":", "/"))
    result = {
        "width": stream["width"],
        "height": stream["height"],
        "rotation": _rotation(stream),
        "sampleAspectRatio": {"num": sar.numerator, "den": sar.denominator},
    }
    validate_document(result, SCHEMA + "#/$defs/sourceGeometry")
    return result


def _dimensions(geometry):
    aspect = _display_aspect(geometry)
    width, height = (
        (320, round(320 / aspect)) if aspect >= 1 else (round(320 * aspect), 320)
    )
    if min(width, height) < 32:
        raise ValueError("The selected display aspect is too narrow for face capture")
    return width, height


def _decode_command(path, destination, index, options, scope, every, size, origin):
    start, end = scope["startTicks"], scope["endTicks"]
    fields = scope["timebase"]
    base = Fraction(fields["num"], fields["den"])
    seek = int(start * base) - 2
    approximate_seek = (
        ["-seek_timestamp", "1", "-ss", str(seek)]
        if seek > max(0, origin * base)
        else []
    )
    width, height = size
    frame_limit = min(300, MAX_PROXY_BYTES // (width * height * 3))
    filters = (
        f"trim=start_pts={start}:end_pts={end},select=not(mod(n\\,{every})),"
        f"showinfo=checksum=0,scale={width}:{height}:flags=bicubic,setsar=1"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-nostdin",
        "-n",
        "-copyts",
        *options,
        *approximate_seek,
        "-i",
        str(path),
        "-map",
        f"0:{index}",
        "-an",
        "-sn",
        "-dn",
        "-filter_threads",
        "1",
        "-vf",
        filters,
        "-fps_mode",
        "passthrough",
        "-frames:v",
        str(frame_limit + 1),
        "-c:v",
        "rawvideo",
        "-threads:v",
        "1",
        "-pix_fmt",
        "bgr24",
        "-f",
        "rawvideo",
        str(destination),
    ], frame_limit


def _decode_log(command):
    with tempfile.TemporaryFile() as errors:
        result = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=errors, check=False, timeout=120
        )
        errors.seek(0)
        data = errors.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Face proxy decoding exceeds its log budget")
    log = data.decode("utf-8", errors="replace")
    if result.returncode:
        raise ValueError(f"Face proxy decoding failed: {log[-1200:]}")
    return log


def _observed_source_ticks(log, scope, frame_limit):
    config = re.findall(r"showinfo[^\n]*config in time_base:\s*(\d+/\d+)", log)
    expected = Fraction(scope["timebase"]["num"], scope["timebase"]["den"])
    if not config or any(Fraction(value) != expected for value in config):
        raise ValueError("Decoded face proxy time base differs from the source clock")
    rows = re.findall(r"showinfo[^\n]*?\bn:\s*(\d+)\s+pts:\s*(-?\d+)\b", log)
    ticks = [int(pts) for _, pts in rows]
    if not 1 <= len(ticks) <= frame_limit:
        raise ValueError(
            "Face proxy has no samples or exceeds its selected frame limit"
        )
    if [int(index) for index, _ in rows] != list(range(len(ticks))) or ticks != sorted(
        set(ticks)
    ):
        raise ValueError("Decoded face proxy frame order or PTS is ambiguous")
    if not scope["startTicks"] <= ticks[0] <= ticks[-1] < scope["endTicks"]:
        raise ValueError("Decoded face proxy samples exceed the selected source range")
    return ticks


def _validate_capture_request(index, scope, every):
    validate_document(scope, SCHEMA + "#/$defs/sourceRange")
    if (
        type(index) is not int
        or index < 0
        or type(every) is not int
        or not 1 <= every <= 120
    ):
        raise ValueError(
            "Face capture needs an explicit stream and bounded frame stride"
        )
    span = scope["endTicks"] - scope["startTicks"]
    scale = Fraction(scope["timebase"]["num"], scope["timebase"]["den"])
    if not 0 < span * scale <= 30:
        raise ValueError("Face capture requires a source range of at most 30 seconds")


def capture_display_proxy(
    source, destination, *, stream_index, source_range, expected_sha256, sample_every
):
    """Decode one short verified source range and retain observed native frame PTS."""
    _validate_capture_request(stream_index, source_range, sample_every)
    source, destination = Path(source).resolve(), Path(destination).resolve()
    options = local_source_arguments(source)
    with fingerprint_stage(verify_on_exit=True):
        source_file = file_fingerprint(source)
        if source_file["sha256"] != expected_sha256:
            raise ValueError("Face capture source bytes differ from the original")
        stream = _source_video(source, stream_index, options)
        scale = source_range["timebase"]
        if Fraction(stream["time_base"]) != Fraction(scale["num"], scale["den"]):
            raise ValueError("Face capture range must use the original video time base")
        raw_origin = stream.get("start_pts")
        origin = None if raw_origin in (None, "N/A") else int(raw_origin)
        geometry = _geometry(stream)
        width, height = _dimensions(geometry)
        command, limit = _decode_command(
            source,
            destination,
            stream_index,
            options,
            source_range,
            sample_every,
            (width, height),
            origin or 0,
        )
        ticks = _observed_source_ticks(_decode_log(command), source_range, limit)
        proxy_file = file_fingerprint(destination)
        if proxy_file["sizeBytes"] != len(ticks) * width * height * 3:
            raise ValueError(
                "Decoded face proxy frame bytes differ from observed timing"
            )
    return {
        "sourceSizeBytes": source_file["sizeBytes"],
        "streamOriginTicks": origin,
        "geometry": geometry,
        "proxy": {
            "sha256": proxy_file["sha256"],
            "width": width,
            "height": height,
            "content": {"x": 0, "y": 0, "width": width, "height": height},
            "sourceTicks": ticks,
        },
    }


def observe_selected_face(resolved, source, request):
    """Observe one selected original stream with a disposable display proxy."""
    preflight_face_job(resolved)
    with tempfile.TemporaryDirectory(prefix="avo-face-proxy-") as directory:
        path = Path(directory).resolve() / "display.bgr"
        measured = capture_display_proxy(
            source,
            path,
            stream_index=request["streamIndex"],
            source_range=request["sourceRange"],
            expected_sha256=request["sourceSha256"],
            sample_every=request["sampleEvery"],
        )
        proxy = measured["proxy"]
        observed = detect_proxy_faces(
            resolved,
            path,
            width=proxy["width"],
            height=proxy["height"],
            frame_count=len(proxy["sourceTicks"]),
            sha256=proxy["sha256"],
        )
    return freeze_face_observation(
        {
            "contractVersion": "1.0.0",
            "source": {
                "sourceId": request["sourceId"],
                "sha256": request["sourceSha256"],
                "sizeBytes": measured["sourceSizeBytes"],
            },
            "geometry": measured["geometry"],
            "streamOriginTicks": measured["streamOriginTicks"],
            "proxy": proxy,
            **{
                key: request[key]
                for key in ("sourceRange", "seed", "minimumOverlap", "maximumGapTicks")
            },
        },
        observed,
    )


def _reference_contact_sheet(path, proxy):
    from PIL import Image, ImageDraw

    width, height = proxy["width"], proxy["height"]
    ticks = proxy["sourceTicks"]
    frame_count = min(6, len(ticks))
    positions = [
        round(Fraction(index * (len(ticks) - 1), frame_count - 1))
        for index in range(frame_count)
    ]
    cell_width, cell_height = 208, 170
    columns = min(3, frame_count)
    rows = (frame_count + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (20, 24, 29))
    draw = ImageDraw.Draw(sheet)
    with Path(path).open("rb") as stream:
        for index, frame_number in enumerate(positions):
            frame_size = width * height * 3
            stream.seek(frame_number * frame_size)
            frame = Image.frombytes(
                "RGB", (width, height), stream.read(frame_size), "raw", "BGR"
            )
            frame.thumbnail((192, 140))
            x, y = (index % columns) * cell_width, (index // columns) * cell_height
            sheet.paste(frame, (x + (cell_width - frame.width) // 2, y + 5))
            draw.text(
                (x + 8, y + 150),
                f"Source PTS {ticks[frame_number]}",
                fill=(238, 241, 244),
            )
    output = BytesIO()
    sheet.save(output, format="PNG")
    return output.getvalue()


def observe_reference_clip(source, clip, python):
    """Observe one sealed local range and prepare a labeled visual contact sheet."""
    with tempfile.TemporaryDirectory(prefix="avo-reference-proxy-") as directory:
        path = Path(directory).resolve() / "display.bgr"
        captured = capture_display_proxy(
            source,
            path,
            stream_index=clip["streamIndex"],
            source_range=clip["sourceRange"],
            expected_sha256=clip["source"]["sha256"],
            sample_every=clip["sampleEvery"],
        )
        proxy = captured["proxy"]
        if captured["sourceSizeBytes"] != clip["source"]["sizeBytes"]:
            raise ValueError("Reference file size differs from the selected source")
        measured = measure_reference_proxy(
            python,
            path,
            width=proxy["width"],
            height=proxy["height"],
            frame_count=len(proxy["sourceTicks"]),
            sha256=proxy["sha256"],
        )
        observation = freeze_reference_motion(
            {
                **{key: clip[key] for key in ("source", "sourceRange", "aspects")},
                "geometry": captured["geometry"],
                "proxy": proxy,
            },
            measured,
        )
        return observation, _reference_contact_sheet(path, proxy)


__all__ = ["capture_display_proxy", "observe_reference_clip", "observe_selected_face"]
