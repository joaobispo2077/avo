"""Input policy for one self-contained local original, never a media playlist."""

from __future__ import annotations

import os
import re

MAX_SOURCE_STREAMS = 64
CLOSED_DEMUXERS = (
    "mov",
    "mp4",
    "m4a",
    "3gp",
    "3g2",
    "mj2",
    "matroska",
    "webm",
    "avi",
    "wav",
    "aiff",
    "flac",
    "mp3",
    "ogg",
    "mpegts",
    "mpeg",
    "mpegvideo",
    "h264",
    "hevc",
    "aac",
    "asf",
    "mxf",
    "dv",
    "mjpeg",
    "flv",
    "nut",
    "w64",
    "caf",
    "ac3",
    "eac3",
    "dts",
    "dnxhd",
    "h263",
    "m4v",
    "av1",
    "obu",
    "png_pipe",
    "jpeg_pipe",
    "bmp_pipe",
    "tiff_pipe",
    "webp_pipe",
)


def _require_native_local_path(path):
    try:
        text = os.fspath(path)
    except TypeError as exc:
        raise ValueError("Original media requires a native local file path") from exc
    if (
        not isinstance(text, str)
        or not text
        or text == "-"
        or "\x00" in text
        or len(text) > 32767
    ):
        raise ValueError("Original media requires a native local file path")
    protocol = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", text)
    drive = re.match(r"^[a-zA-Z]:[\\/]", text)
    if text.startswith(("\\\\", "//")) or (protocol and not drive):
        raise ValueError("Only native local original files are supported")


def local_source_arguments(path, *, literal_still=False):
    """Return input options before ``-i``; never admit a nested-file demuxer."""
    _require_native_local_path(path)
    if type(literal_still) is not bool:
        raise ValueError("Literal local image input must be explicitly boolean")
    formats = (*CLOSED_DEMUXERS, "image2") if literal_still else CLOSED_DEMUXERS
    arguments = [
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        ",".join(formats),
        "-max_streams",
        str(MAX_SOURCE_STREAMS),
    ]
    if literal_still:
        # Generic image2 may expand a sequence; this path always names one file.
        arguments.extend(["-f", "image2", "-pattern_type", "none"])
    return arguments
