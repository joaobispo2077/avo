"""Batch-transcribe a source directory with one shared local PT-BR runtime."""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from avo.transcribe import (
    DEFAULT_MODEL,
    LocalTranscriber,
    PTBRArgumentParser,
    inspect_cache,
    source_fingerprint,
    transcript_path,
    transcribe_one,
    validate_model_name,
)


VIDEO_EXTS = {".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV", ".avi", ".AVI", ".m4v"}
RuntimeFactory = Callable[..., LocalTranscriber]


@dataclass
class BatchResult:
    found: int
    cached: int
    transcribed: int
    failures: list[tuple[Path, str]]


def find_videos(videos_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in videos_dir.iterdir()
        if path.is_file() and path.suffix in VIDEO_EXTS
    )


def transcribe_directory(
    videos_dir: Path,
    edit_dir: Path | None = None,
    workers: int = 1,
    model: str = DEFAULT_MODEL,
    model_dir: Path | None = None,
    device: str = "auto",
    compute_type: str = "auto",
    force: bool = False,
    runtime_factory: RuntimeFactory = LocalTranscriber,
    verbose: bool = True,
) -> BatchResult:
    if workers < 1:
        raise ValueError("worker count must be at least 1")
    videos_dir = videos_dir.resolve()
    if not videos_dir.is_dir():
        raise ValueError(f"not a directory: {videos_dir}")
    model = validate_model_name(model)
    edit_dir = (edit_dir or (videos_dir / "edit")).resolve()
    videos = find_videos(videos_dir)
    if not videos:
        return BatchResult(0, 0, 0, [])

    fingerprints = {video: source_fingerprint(video) for video in videos}
    cached = []
    pending = []
    for video in videos:
        state = inspect_cache(
            transcript_path(video, edit_dir), fingerprints[video], model
        )
        if state == "valid" and not force:
            cached.append(video)
        else:
            pending.append(video)

    if verbose:
        print(
            f"found {len(videos)} videos "
            f"({len(cached)} cached, {len(pending)} to transcribe)"
        )
    if not pending:
        if verbose:
            print("nothing to do")
        return BatchResult(len(videos), len(cached), 0, [])

    runtime = runtime_factory(
        model=model,
        model_dir=model_dir,
        device=device,
        compute_type=compute_type,
        num_workers=workers,
    )
    failures: list[tuple[Path, str]] = []
    completed = 0
    started = time.monotonic()

    def run_one(video: Path) -> Path:
        return transcribe_one(
            video,
            edit_dir,
            runtime=runtime,
            model=model,
            force=force,
            verbose=False,
            fingerprint=fingerprints[video],
        )

    if workers == 1:
        for video in pending:
            try:
                out = run_one(video)
                completed += 1
                if verbose:
                    print(f"  + {video.stem} -> {out.name}")
            except Exception as exc:
                failures.append((video, str(exc)))
                if verbose:
                    print(f"  x {video.stem} FAILED: {exc}")
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, video): video for video in pending}
            for future in as_completed(futures):
                video = futures[future]
                try:
                    out = future.result()
                    completed += 1
                    if verbose:
                        print(f"  + {video.stem} -> {out.name}")
                except Exception as exc:
                    failures.append((video, str(exc)))
                    if verbose:
                        print(f"  x {video.stem} FAILED: {exc}")

    if verbose:
        print(f"done in {time.monotonic() - started:.1f}s")
    return BatchResult(len(videos), len(cached), completed, failures)


def build_parser() -> argparse.ArgumentParser:
    parser = PTBRArgumentParser(
        description="Batch-transcribe a directory locally in PT-BR"
    )
    parser.add_argument("videos_dir", type=Path)
    parser.add_argument("--edit-dir", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--compute-type", default="auto")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        result = transcribe_directory(
            args.videos_dir,
            args.edit_dir,
            workers=args.workers,
            model=args.model,
            model_dir=args.model_dir,
            device=args.device,
            compute_type=args.compute_type,
            force=args.force,
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if result.found == 0:
        raise SystemExit(f"no videos found in {args.videos_dir.resolve()}")
    if result.failures:
        summary = "\n".join(f"  {video.name}: {error}" for video, error in result.failures)
        raise SystemExit(f"{len(result.failures)} transcription failures:\n{summary}")


if __name__ == "__main__":
    main()
