"""Create and verify a lossless RGBA source for the measured editor profile."""

import os
import tempfile
from fractions import Fraction
from pathlib import Path

from avo.timeline.contracts import file_fingerprint

from .proof_generated import _capture, _probe


def _rgba_hashes(path):
    payload = _capture(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "rawvideo",
            "-threads:v",
            "1",
            "-pix_fmt",
            "rgba",
            "-f",
            "framehash",
            "-hash",
            "sha256",
            "-",
        ],
        path,
    )
    return [
        row.rsplit(",", 1)[-1].strip()
        for row in payload.splitlines()
        if row and not row.startswith("#")
    ]


def _verify(path, source_video, hashes, fps):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Editor alpha copy must be an owned media file")
    video = _probe(path)
    if (
        (video.get("width"), video.get("height"))
        != (source_video["width"], source_video["height"])
        or video.get("codec_name") != "png"
        or video.get("pix_fmt") != "rgba"
        or video.get("start_pts") != 0
        or Fraction(video["avg_frame_rate"]) != fps
        or _rgba_hashes(path) != hashes
    ):
        raise ValueError("Editor alpha copy changes its original clock, RGB or alpha")


def _encode(source, target, fps):
    _capture(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-an",
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-c:v",
            "png",
            "-pix_fmt",
            "rgba",
            "-threads:v",
            "1",
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            str(target),
        ],
        source,
    )


def editor_alpha_copy(asset, fps):
    source = Path(asset["path"]).resolve()
    source_video = asset["video"]
    directory = source.parent / "editor-alpha"
    if directory.resolve() != directory:
        raise ValueError(
            "Editor alpha copy directory must remain with the admitted source"
        )
    directory.mkdir(exist_ok=True)
    output = directory / ("png-rgba-v1-" + asset["record"]["output"]["sha256"] + ".mov")
    hashes = _rgba_hashes(source)
    if len(hashes) != int(source_video["nb_read_frames"]):
        raise ValueError("Editor alpha copy needs the complete verified source frames")
    if not output.exists():
        with tempfile.TemporaryDirectory(prefix="alpha-", dir=directory) as staging:
            candidate = Path(staging) / "source.mov"
            _encode(source, candidate, fps)
            _verify(candidate, source_video, hashes, fps)
            try:
                os.link(candidate, output)
            except FileExistsError:
                pass
    _verify(output, source_video, hashes, fps)
    return file_fingerprint(output)
