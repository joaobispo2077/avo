"""Small synthetic sources for editing-craft tests, never production footage.

Factories return source files or fixture occurrence descriptions, not approved
canonical decisions. Existing footage_project_factory owns workspace setup.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from tests.fixtures.timeline.build_fixtures import sha256

MANIFEST = Path(__file__).parent / "fixtures" / "editing_craft" / "corpus.json"


def _frames(count, size, bit_depth, alpha):
    width, height = size
    y, x = np.indices((height, width))
    maximum = (1 << bit_depth) - 1
    dtype = np.uint8 if bit_depth == 8 else np.dtype("<u2")
    for index in range(count):
        multiplier = 1 if bit_depth == 8 else 257
        pixels = np.stack(
            (
                (x * 5 * multiplier + index * 1031) % (maximum + 1),
                (y * 7 * multiplier + index * 2053) % (maximum + 1),
                ((x + y) * 3 * multiplier + index * 4099) % (maximum + 1),
            ),
            axis=-1,
        ).astype(dtype)
        label = Image.new("1", size)
        ImageDraw.Draw(label).text((4, 4), f"FRAME {index:03d}", fill=1)
        mask = np.asarray(label, dtype=bool)
        pixels[mask] = maximum
        if alpha:
            opacity = np.zeros((height, width), dtype=np.uint8)
            opacity[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4] = 180
            opacity[mask] = 255
            pixels = np.dstack((pixels, opacity))
        yield pixels.tobytes()


def labeled_video(
    path: Path,
    *,
    fps=Fraction(24),
    frame_count=24,
    size=(160, 90),
    bit_depth=8,
    alpha=False,
    sar=Fraction(1),
    rotation=0,
) -> Path:
    """Encode bounded, numbered RGB frames with exact rate/display metadata.

    Use MP4 for rotation metadata; MKV/FFV1 covers lossless RGB, alpha and true
    16-bit gradients. Sixteen-bit gradients deliberately contain low-bit detail.
    """
    path = Path(path)
    fps, sar = Fraction(fps), Fraction(sar)
    if (
        type(frame_count) is not int
        or not 1 <= frame_count <= 120
        or len(size) != 2
        or any(type(v) is not int or not 32 <= v <= 320 for v in size)
        or not 1 <= fps <= 120
        or not 0 < sar <= 4
        or bit_depth not in {8, 16}
        or (alpha and bit_depth != 8)
        or rotation not in {0, 90, 180, 270}
        or path.suffix not in {".mkv", ".mov", ".mp4"}
        or (rotation and path.suffix != ".mp4")
        or (path.suffix == ".mp4" and (alpha or bit_depth != 8))
    ):
        raise ValueError("Unsupported or unbounded synthetic video request")
    path.parent.mkdir(parents=True, exist_ok=True)
    pixel_format = "rgba" if alpha else "rgb24" if bit_depth == 8 else "rgb48le"
    output_format = "bgra" if bit_depth == 8 else "gbrp16le"
    codec = "ffv1"
    if path.suffix == ".mov":
        codec = "png"
        output_format = pixel_format if bit_depth == 8 else "rgb48be"
    if path.suffix == ".mp4":
        codec, output_format = "libx264", "yuv444p"
    with tempfile.TemporaryDirectory(prefix="craft-source-", dir=path.parent) as work:
        encoded = Path(work) / ("unrotated" + path.suffix) if rotation else path
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-n",
                "-f",
                "rawvideo",
                "-pixel_format",
                pixel_format,
                "-video_size",
                f"{size[0]}x{size[1]}",
                "-framerate",
                str(fps),
                "-i",
                "pipe:0",
                "-frames:v",
                str(frame_count),
                "-vf",
                f"setsar={sar}",
                "-c:v",
                codec,
                "-pix_fmt",
                output_format,
                str(encoded),
            ],
            input=b"".join(_frames(frame_count, size, bit_depth, alpha)),
            capture_output=True,
            check=True,
        )
        if rotation:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-n",
                    "-display_rotation",
                    str(rotation),
                    "-i",
                    str(encoded),
                    "-c",
                    "copy",
                    str(path),
                ],
                capture_output=True,
                check=True,
            )
    return path


def _pcm(path, values, sample_rate):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    samples = np.rint(np.clip(values, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(values.shape[1])
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(samples.tobytes())
    return path


def channel_impulses(path: Path, *, sample_rate=48000, sample_count=48000) -> Path:
    """Write separated left/right impulses at exactly 1/4 and 1/2 duration."""
    if sample_rate not in {44100, 48000, 96000} or not 4 <= sample_count <= 144000:
        raise ValueError("Unsupported or unbounded synthetic audio request")
    values = np.zeros((sample_count, 2))
    values[sample_count // 4, 0] = 0.5
    values[sample_count // 2, 1] = -0.25
    return _pcm(path, values, sample_rate)


def synthetic_sfx(path: Path, *, kind="whoosh", sample_rate=48000, sample_count=24000):
    """Synthesize MIT test sounds; these are not real library rights evidence."""
    if (
        kind not in {"whoosh", "impact", "double-attack", "silence"}
        or sample_rate not in {44100, 48000, 96000}
        or type(sample_count) is not int
        or not 32 <= sample_count <= 144000
    ):
        raise ValueError("Unsupported or unbounded synthetic SFX request")
    values = np.zeros(sample_count)
    if kind == "whoosh":
        envelope = np.sin(np.linspace(0, np.pi, sample_count)) ** 2
        values = np.random.default_rng(17).uniform(-0.3, 0.3, sample_count) * envelope
    elif kind in {"impact", "double-attack"}:
        offsets = [sample_count // 4]
        if kind == "double-attack":
            offsets.append(sample_count // 2)
        for offset in offsets:
            t = np.arange(sample_count - offset) / sample_rate
            values[offset:] += 0.4 * np.cos(2 * np.pi * 880 * t) * np.exp(-40 * t)
    return _pcm(path, values[:, None], sample_rate)


def repeated_occurrences(source: Path, *, source_frames=12, gap_frames=3):
    """Describe two occurrences of identical source bytes, with distinct IDs."""
    if type(source_frames) is not int or not 1 <= source_frames <= 120:
        raise ValueError("Invalid synthetic source range")
    if type(gap_frames) is not int or not 0 <= gap_frames <= 120:
        raise ValueError("Invalid synthetic occurrence gap")
    fingerprint = sha256(Path(source))
    return [
        {
            "occurrenceId": f"occurrence-{index + 1}",
            "sourceSha256": fingerprint,
            "sourceRangeFrames": [0, source_frames],
            "programRangeFrames": [start, start + source_frames],
        }
        for index in range(2)
        for start in [index * (source_frames + gap_frames)]
    ]


def build_corpus(directory: Path):
    """Materialize only the declared small corpus and report actual digests."""
    directory = Path(directory)
    definition = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = {}
    for name, parameters in definition["video"].items():
        path = labeled_video(directory / name, **parameters)
        records[name] = {"sha256": sha256(path), "sizeBytes": path.stat().st_size}
    parameters = definition["audio"]["channel-impulses.wav"]
    audio = channel_impulses(
        directory / "channel-impulses.wav",
        sample_rate=parameters["sampleRate"],
        sample_count=parameters["sampleCount"],
    )
    records[audio.name] = {"sha256": sha256(audio), "sizeBytes": audio.stat().st_size}
    for name, parameters in definition["sfx"].items():
        path = synthetic_sfx(directory / name, **parameters["synthesis"])
        records[name] = {
            "sha256": sha256(path),
            "sizeBytes": path.stat().st_size,
            "rightsFixtureState": parameters["rightsFixtureState"],
        }
    occurrences = definition["occurrences"]
    return {
        "schemaVersion": "1.0.0",
        "sources": records,
        "occurrences": repeated_occurrences(
            directory / occurrences["source"],
            source_frames=occurrences["sourceRangeFrames"][1],
            gap_frames=occurrences["gapFrames"],
        ),
    }
