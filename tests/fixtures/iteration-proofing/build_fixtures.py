"""Build deterministic synthetic media for iteration-proofing tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(args: Iterable[str]) -> None:
    subprocess.run(list(args), check=True, capture_output=True)


def _video_tail(output: Path, *, audio: bool = False) -> list[str]:
    result = [
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        "-pix_fmt",
        "yuv420p",
    ]
    if audio:
        result += ["-c:a", "aac", "-b:a", "64k", "-ar", "48000", "-shortest"]
    result += [
        "-map_metadata",
        "-1",
        "-metadata",
        "creation_time=1970-01-01T00:00:00Z",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
    ]
    if audio:
        result += ["-flags:a", "+bitexact"]
    return [*result, str(output)]


def _source(ffmpeg: str, output: Path) -> None:
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=12:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            *_video_tail(output, audio=True),
        ]
    )


def _proof_ancestry(ffmpeg: str, output_dir: Path) -> list[Path]:
    source = output_dir / "original-source.mp4"
    _source(ffmpeg, source)
    proof = output_dir / "prior-proof.mp4"
    shutil.copyfile(source, proof)
    return [source, proof]


def _speech_joins(ffmpeg: str, output_dir: Path) -> list[Path]:
    output = output_dir / "speech-joins.wav"
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=330:sample_rate=48000:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=550:sample_rate=48000:duration=1",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            "-map_metadata",
            "-1",
            str(output),
        ]
    )
    return [output]


def _sfx_transient(ffmpeg: str, output_dir: Path) -> list[Path]:
    output = output_dir / "sfx-transient.wav"
    expression = "if(lt(t\\,0.25)\\,0\\,if(lt(t\\,0.27)\\,0.9*sin(2*PI*1200*t)\\,0))"
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc={expression}:s=48000:d=1",
            "-c:a",
            "pcm_s16le",
            "-map_metadata",
            "-1",
            str(output),
        ]
    )
    return [output]


def _moving_overlay(ffmpeg: str, output_dir: Path) -> list[Path]:
    output = output_dir / "moving-overlay.mp4"
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x102030:size=160x90:rate=12:duration=3",
            "-f",
            "lavfi",
            "-i",
            "color=c=0xffcc00:size=24x18:rate=12:duration=3",
            "-filter_complex",
            "[0:v][1:v]overlay=x='mod(t*40\\,136)':y=36[out]",
            "-map",
            "[out]",
            *_video_tail(output),
        ]
    )
    return [output]


def _vfr_stills(ffmpeg: str, output_dir: Path) -> list[Path]:
    output = output_dir / "vfr-stills.mp4"
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=12:duration=4",
            "-vf",
            "select='eq(mod(n\\,4)\\,0)+eq(mod(n\\,9)\\,0)'",
            "-fps_mode",
            "vfr",
            *_video_tail(output),
        ]
    )
    return [output]


def _hybrid_pacing(ffmpeg: str, output_dir: Path) -> list[Path]:
    output = output_dir / "hybrid-pacing.mp4"
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=6:duration=12",
            *_video_tail(output),
        ]
    )
    return [output]


def _caption_privacy(ffmpeg: str, output_dir: Path) -> list[Path]:
    output = output_dir / "caption-privacy.mp4"
    filters = "drawbox=x=6:y=64:w=148:h=20:color=black@0.8:t=fill,drawbox=x=110:y=8:w=40:h=26:color=red@1:t=fill"
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x6688aa:size=160x90:rate=6:duration=3",
            "-vf",
            filters,
            *_video_tail(output),
        ]
    )
    return [output]


def _long_form_watch(ffmpeg: str, output_dir: Path) -> list[Path]:
    output = output_dir / "long-form-watch.mp4"
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=1/10:duration=1200",
            *_video_tail(output),
        ]
    )
    return [output]


BUILDERS: dict[str, Callable[[str, Path], list[Path]]] = {
    "proof-ancestry": _proof_ancestry,
    "speech-joins": _speech_joins,
    "sfx-transient": _sfx_transient,
    "moving-overlay": _moving_overlay,
    "vfr-stills": _vfr_stills,
    "hybrid-pacing": _hybrid_pacing,
    "caption-privacy": _caption_privacy,
    "long-form-watch": _long_form_watch,
}


def build_fixture_set(
    output_dir: Path,
    *,
    ffmpeg: str = "ffmpeg",
    only: set[str] | None = None,
) -> dict[str, object]:
    if shutil.which(ffmpeg) is None:
        raise RuntimeError(f"ffmpeg executable not found: {ffmpeg}")
    requested = set(BUILDERS) if only is None else set(only)
    unknown = requested - set(BUILDERS)
    if unknown:
        raise ValueError(f"unknown fixture scenarios: {', '.join(sorted(unknown))}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, dict[str, object]] = {}
    for scenario in sorted(requested):
        for path in BUILDERS[scenario](ffmpeg, output_dir):
            outputs[path.name] = {
                "sha256": sha256(path),
                "byteSize": path.stat().st_size,
            }
    manifest: dict[str, object] = {
        "schemaVersion": "1.0.0",
        "scenarios": sorted(requested),
        "files": dict(sorted(outputs.items())),
    }
    (output_dir / "generated-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--only", action="append", choices=sorted(BUILDERS))
    args = parser.parse_args(argv)
    build_fixture_set(
        args.output_dir,
        ffmpeg=args.ffmpeg,
        only=set(args.only) if args.only else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
