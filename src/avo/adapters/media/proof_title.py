"""Render explicit inert title data with locked original authorial/font files."""

import hashlib
import subprocess
import tempfile
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

from avo.timeline.contracts import file_fingerprint


def _authorial(parameters, execution, maximum):
    from . import proof_executor as native

    _source, path, digest = native._source_identity(
        parameters, execution["canonicalInputLock"]
    )
    if not path.is_file() or path.stat().st_size > maximum:
        raise RuntimeError("Title authorial input is missing or exceeds its byte limit")
    if file_fingerprint(path)["sha256"] != digest:
        raise RuntimeError("Title authorial input fingerprint changed")
    return path


def admit_title(item, execution):
    if set(item["fontSource"]) != {"sourceId", "source"}:
        raise RuntimeError("Unsupported title font source declaration")
    project = _authorial(item, execution, 64 * 1024 * 1024)
    font = _authorial(item["fontSource"], execution, 32 * 1024 * 1024)
    with font.open("rb") as stream:
        magic = stream.read(4)
    if magic not in {b"\x00\x01\x00\x00", b"OTTO"}:
        raise RuntimeError("Title requires a pinned TrueType/OpenType font")
    from PIL import ImageFont

    try:
        ImageFont.truetype(str(font), size=16)
    except (OSError, ValueError) as exc:
        raise RuntimeError("Title font could not be decoded") from exc
    return {"item": item, "path": project, "fontPath": font}


@contextmanager
def title_command(source, directory, spec, fps, count, fade_filters, *, start_frame=0):
    data = source["item"]["title"]
    if data["canvasWidth"] * spec["height"] != data["canvasHeight"] * spec["width"]:
        raise RuntimeError("Title preview changes canonical canvas aspect ratio")
    scale = Fraction(spec["width"], data["canvasWidth"])
    x, y = round(data["x"] * scale), round(data["y"] * scale)
    size = max(1, round(data["fontSize"] * scale))
    xexpr = f"{x}-text_w/2" if data["anchor"] == "center" else str(x)
    yexpr = f"{y}-text_h/2" if data["anchor"] == "center" else str(y)
    with tempfile.TemporaryDirectory(prefix="title-", dir=directory) as folder:
        folder = Path(folder)
        with source["fontPath"].open("rb") as stream:
            font = stream.read(32 * 1024 * 1024 + 1)
        if (
            len(font) > 32 * 1024 * 1024
            or hashlib.sha256(font).hexdigest()
            != source["item"]["fontSource"]["source"]["sha256"]
        ):
            raise RuntimeError("Title font changed before rendering")
        (folder / "font.ttf").write_bytes(font)
        (folder / "title.txt").write_text(data["text"], encoding="utf-8")
        filters = (
            f"drawtext=fontfile=font.ttf:textfile=title.txt:expansion=none:fontsize={size}:"
            f"fontcolor=0x{data['color'][1:]}:x={xexpr}:y={yexpr}{fade_filters},format=bgra,"
            f"trim=start_frame={start_frame},setpts=PTS-STARTPTS"
        )
        yield (
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black@0.0:s={spec['width']}x{spec['height']}:r={fps},format=rgba",
                "-vf",
                filters,
                "-frames:v",
                str(count - start_frame),
                "-an",
                "-pix_fmt",
                "bgra",
                "-r",
                str(fps),
                "-fps_mode",
                "cfr",
            ],
            folder,
        )


def render_title(source, output, spec, fps, count, fade_filters, *, start_frame=0):
    with title_command(
        source,
        Path(output).parent,
        spec,
        fps,
        count,
        fade_filters,
        start_frame=start_frame,
    ) as (arguments, folder):
        result = subprocess.run(
            [*arguments, "-c:v", "ffv1", str(Path(output).resolve())],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError("Title render failed: " + result.stderr[-4096:])
