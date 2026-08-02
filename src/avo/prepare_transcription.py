"""Download a multilingual model for offline PT-BR transcription."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from avo.transcribe import (
    DEFAULT_MODEL,
    MODEL_FILES,
    resolve_model_dir,
    validate_model_dir,
    validate_model_name,
)


Downloader = Callable[..., str]


def _download_model(model: str, output_dir: str) -> str:
    try:
        from faster_whisper.utils import download_model
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed; run: python -m pip install -e ."
        ) from exc
    return download_model(model, output_dir=output_dir)


def prepare_model(
    model: str = DEFAULT_MODEL,
    model_dir: Path | None = None,
    downloader: Downloader | None = None,
) -> Path:
    model = validate_model_name(model)
    destination = resolve_model_dir(model, model_dir)
    if all((destination / name).is_file() for name in MODEL_FILES):
        return destination

    destination.mkdir(parents=True, exist_ok=True)
    try:
        (downloader or _download_model)(model, output_dir=str(destination))
        validate_model_dir(destination, model)
    except Exception as exc:
        raise RuntimeError(
            f"failed to prepare multilingual model {model} at {destination}: {exc}"
        ) from exc
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a multilingual Whisper model for local PT-BR transcription"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        destination = prepare_model(args.model, args.model_dir)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"local PT-BR model ready: {destination}")


if __name__ == "__main__":
    main()
