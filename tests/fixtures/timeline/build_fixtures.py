"""Deterministic ffmpeg media fixtures for timeline vertical tests.

This is a Python test-data flow, not a per-video repair helper. It always creates
new synthetic raw sources and never edits project footage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(args: Iterable[str]) -> None:
    subprocess.run(list(args), check=True, capture_output=True)


def _base_command(ffmpeg: str, duration: float, frequency: int) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=320x180:rate=30:duration={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
    ]


def _encode(
    ffmpeg: str,
    output: Path,
    *,
    duration: float,
    frequency: int,
    audio_filter: str = "anull",
) -> None:
    command = _base_command(ffmpeg, duration, frequency)
    command += [
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-af",
        audio_filter,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-ar",
        "48000",
        "-map_metadata",
        "-1",
        "-metadata",
        "creation_time=1970-01-01T00:00:00Z",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output),
    ]
    _run(command)


def build_fixture_set(output_dir: Path, *, ffmpeg: str = "ffmpeg") -> dict[str, object]:
    if shutil.which(ffmpeg) is None:
        raise RuntimeError(f"ffmpeg executable not found: {ffmpeg}")
    output_dir.mkdir(parents=True, exist_ok=True)
    definitions = {
        "clean-clock.mp4": (4.0, 440, "anull"),
        "audio-plus-128ms.mp4": (4.0, 550, "adelay=128|128"),
        "linear-drift.mp4": (6.0, 660, "asetrate=47952,aresample=48000"),
        "piecewise-drift.mp4": (6.0, 770, "asetrate=48048,aresample=48000"),
        "source-a.mp4": (3.0, 880, "anull"),
        "source-b.mp4": (3.0, 990, "anull"),
    }
    outputs: dict[str, dict[str, object]] = {}
    for name, (duration, frequency, audio_filter) in definitions.items():
        path = output_dir / name
        _encode(
            ffmpeg,
            path,
            duration=duration,
            frequency=frequency,
            audio_filter=audio_filter,
        )
        outputs[name] = {"sha256": sha256(path), "byteSize": path.stat().st_size}
    manifest = {"schemaVersion": "1.0.0", "files": outputs}
    (output_dir / "generated-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args(argv)
    build_fixture_set(args.output_dir, ffmpeg=args.ffmpeg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
