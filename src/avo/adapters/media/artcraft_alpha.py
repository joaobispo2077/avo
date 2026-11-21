"""Pack exact generated ArtCraft alpha frames for the existing proof renderer."""

from __future__ import annotations

import hashlib
import json
import os
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import file_fingerprint, fingerprint_stage

from .editor_alpha import _rgba_hashes
from .proof_generated import _capture, _probe

__all__ = ["observe_alpha_sequence", "pack_alpha_sequence"]


def pack_alpha_sequence(frames, contract, output, *, output_root):
    """Produce one lossless preview clip and independently verify every decoded frame."""
    output = _owned_output(output, output_root)
    if output.exists():
        return observe_alpha_sequence(frames, contract, output, output_root=output_root)
    rate = contract["frameRate"]
    fps = Fraction(rate["numerator"], rate["denominator"])
    with TemporaryDirectory(prefix="artcraft-alpha-", dir=output.parent) as staging:
        candidate = Path(staging) / "alpha.mkv"
        with fingerprint_stage(verify_on_exit=True):
            directory, hashes = _verified_source_sequence(frames, contract)
            _encode_alpha(directory, candidate, fps, len(hashes))
            _verify_packed_alpha(candidate, contract, fps, hashes)
        try:
            os.link(candidate, output)
        except FileExistsError:
            pass
    return _verify_packed_alpha(output, contract, fps, hashes)


def observe_alpha_sequence(frames, contract, output, *, output_root):
    """Compare existing media to exact native frames without generating new files."""
    output = _owned_output(output, output_root)
    rate = contract["frameRate"]
    fps = Fraction(rate["numerator"], rate["denominator"])
    with fingerprint_stage(reuse_current=True, verify_on_exit=True):
        _, hashes = _verified_source_sequence(frames, contract)
        return _verify_packed_alpha(output, contract, fps, hashes)


def _owned_output(output, output_root):
    output, root = Path(output), Path(output_root)
    if not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir():
        raise ArtCraftError("ArtCraft needs one exact existing alpha output root")
    if (
        not output.is_absolute()
        or output.resolve() != output
        or not output.is_relative_to(root)
        or output.suffix != ".mkv"
    ):
        raise ArtCraftError(
            "ArtCraft alpha clip must be an exact MKV inside its declared output root"
        )
    if not output.parent.is_dir():
        raise ArtCraftError("ArtCraft alpha clip needs an existing owned output folder")
    return output


def _verified_source_sequence(frames, contract):
    if contract["alpha"] != "straight" or contract["color"] != "srgb":
        raise ArtCraftError("ArtCraft alpha sequence requires straight sRGB pixels")
    if not frames or len(frames) != contract["frameCount"]:
        raise ArtCraftError(
            "ArtCraft alpha source sequence differs from the declared frame count"
        )
    directory = Path(frames[0]["locator"]).parent
    dimensions = contract["width"], contract["height"]
    hashes = []
    for number, fingerprint in enumerate(frames, 1):
        path = directory / f"frame_{number:05d}.png"
        hashes.append(_verified_rgba(path, fingerprint, dimensions))
    return directory, hashes


def _verified_rgba(path, fingerprint, dimensions):
    from PIL import Image

    if (
        not path.is_absolute()
        or str(path) != fingerprint["locator"]
        or path.resolve() != path
    ):
        raise ArtCraftError("ArtCraft alpha frame path differs from its owned sequence")
    if path.stat().st_nlink != 1 or file_fingerprint(path) != fingerprint:
        raise ArtCraftError("ArtCraft alpha frame fingerprint changed")
    with Image.open(path) as image:
        if image.format != "PNG" or image.mode != "RGBA" or image.size != dimensions:
            raise ArtCraftError(
                "ArtCraft alpha input must contain the original RGBA PNG canvas"
            )
        return hashlib.sha256(image.tobytes()).hexdigest()


def _encode_alpha(directory, output, fps, frames):
    pattern = str(directory).replace("%", "%%") + os.sep + "frame_%05d.png"
    _capture(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-xerror",
            "-n",
            "-f",
            "image2",
            "-framerate",
            str(fps),
            "-start_number",
            "1",
            "-start_number_range",
            "1",
            "-i",
            pattern,
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "bgra",
            "-color_range",
            "pc",
            "-colorspace",
            "rgb",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "iec61966-2-1",
            "-threads:v",
            "1",
            "-fps_mode",
            "passthrough",
            "-frames:v",
            str(frames),
            "-f",
            "matroska",
            str(output),
        ],
        directory,
    )


def _verify_packed_alpha(path, contract, fps, hashes):
    if path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1:
        raise ArtCraftError("ArtCraft packed alpha must be an owned regular media file")
    video = _probe(path)
    expected = ("ffv1", "bgra", contract["width"], contract["height"], 0)
    observed = tuple(
        video.get(key)
        for key in ("codec_name", "pix_fmt", "width", "height", "start_pts")
    )
    if observed != expected or Fraction(video["avg_frame_rate"]) != fps:
        raise ArtCraftError("ArtCraft packed alpha changed the canvas or clock")
    _verify_srgb_signaling(video)
    streams = _capture(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        path,
    )
    if streams.strip() != "video" or _rgba_hashes(path) != hashes:
        raise ArtCraftError(
            "ArtCraft packed clip changed the native RGBA frames or added another stream"
        )
    _verify_frame_timestamps(path, video, fps, len(hashes))
    return {
        "fingerprint": file_fingerprint(path),
        "rgbaFrameHashes": hashes,
        "frameRate": contract["frameRate"],
    }


def _verify_srgb_signaling(video):
    expected = {"color_range": "pc", "color_space": "gbr"}
    optional = {"color_primaries": "bt709", "color_transfer": "iec61966-2-1"}
    for key in video.keys() & optional.keys():
        expected[key] = optional[key]
    if any(video.get(key) != value for key, value in expected.items()):
        raise ArtCraftError("ArtCraft packed alpha changed the selected sRGB color")


def _verify_frame_timestamps(path, video, fps, count):
    rows = json.loads(
        _capture(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_frames",
                "-show_entries",
                "frame=best_effort_timestamp",
                "-of",
                "json",
                str(path),
            ],
            path,
        )
    )["frames"]
    ticks_per_frame = 1 / (fps * Fraction(video["time_base"]))
    expected = [int(index * ticks_per_frame + Fraction(1, 2)) for index in range(count)]
    if [row.get("best_effort_timestamp") for row in rows] != expected:
        raise ArtCraftError("ArtCraft packed alpha changed its exact frame timestamps")
