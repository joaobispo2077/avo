"""Verify one literal, bounded original still without expanding image sequences."""

import json
import subprocess
import warnings
from pathlib import Path

from PIL import Image

_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"})
_CODECS = {"PNG": "png", "JPEG": "mjpeg", "BMP": "bmp", "TIFF": "tiff", "WEBP": "webp"}
_MAX_PIXELS = 64_000_000
_MAX_DIMENSION = 16_384


def _image_codec(path):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            width, height = image.size
            if (
                min(width, height) <= 0
                or max(width, height) > _MAX_DIMENSION
                or width * height > _MAX_PIXELS
            ):
                raise ValueError("image exceeds supported dimensions")
            if image.format not in _CODECS:
                raise ValueError("unsupported image container")
            if getattr(image, "n_frames", 1) != 1 or getattr(
                image, "is_animated", False
            ):
                raise ValueError("animated or multi-frame image is not a still")
            return _CODECS[image.format]


def _single_stream(value):
    if not isinstance(value, dict):
        raise ValueError("image probe response must be an object")
    streams = value.get("streams")
    if (
        not isinstance(streams, list)
        or len(streams) != 1
        or not isinstance(streams[0], dict)
    ):
        raise ValueError("exactly one decoded image stream is required")
    return streams[0]


def _decoded_frame(path, expected_codec):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-f",
            "image2",
            "-pattern_type",
            "none",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,codec_name,nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    stream = _single_stream(json.loads(result.stdout))
    if (
        stream.get("codec_type") != "video"
        or stream.get("codec_name") != expected_codec
    ):
        raise ValueError("decoded codec contradicts the supported image container")
    count = stream.get("nb_read_frames")
    if type(count) is not int and (not isinstance(count, str) or not count.isdecimal()):
        raise ValueError("decoded frame count is unknown")
    if int(count) != 1:
        raise ValueError("exactly one decoded frame is required")
    return {"codecName": expected_codec, "decodedFrameCount": 1}


def verify_literal_still(path: Path) -> dict[str, str | int]:
    """Admit only one image, never a sequence, animation or renamed video."""
    path = Path(path)
    try:
        if (
            not path.is_absolute()
            or path.suffix.lower() not in _SUFFIXES
            or not path.is_file()
        ):
            raise ValueError("an existing absolute supported image path is required")
        codec = _image_codec(path)
        return _decoded_frame(path, codec)
    except (
        OSError,
        ValueError,
        EOFError,
        SyntaxError,
        subprocess.SubprocessError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError(f"Cannot verify still {path}: {exc}") from exc
