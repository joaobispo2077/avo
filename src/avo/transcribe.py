"""Offline transcription for the AVO local editing workflow.

Normal transcription only loads prepared local model files. Run
prepare_transcription.py once to download a multilingual model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable


DEFAULT_MODEL = "small"
ENGINE = "faster-whisper"
ENGINE_LANGUAGE = "pt"
LANGUAGE_CODE = "pt-BR"
SCHEMA_VERSION = 1
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")


def validate_model_name(model: str) -> str:
    model = model.strip()
    if not model:
        raise ValueError("model name cannot be empty")
    if model.lower().endswith(".en"):
        raise ValueError(
            "English-only Whisper models are unsupported; "
            "use a multilingual model for PT-BR"
        )
    return model


def default_model_root() -> Path:
    configured = os.environ.get("AVO_MODEL_DIR") or os.environ.get("VIDEO_USE_MODEL_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".cache" / "video-use" / "models").resolve()


def resolve_model_dir(model: str = DEFAULT_MODEL, model_dir: Path | None = None) -> Path:
    model = validate_model_name(model)
    if model_dir is not None:
        return model_dir.expanduser().resolve()
    return (default_model_root() / model).resolve()


def validate_model_dir(model_dir: Path, model: str = DEFAULT_MODEL) -> None:
    missing = [name for name in MODEL_FILES if not (model_dir / name).is_file()]
    if missing:
        command = f"python -m avo.prepare_transcription --model {model}"
        raise RuntimeError(
            f"local PT-BR model is not prepared at {model_dir}; "
            f"missing {', '.join(missing)}. Run: {command}"
        )


def package_version() -> str:
    try:
        return version("faster-whisper")
    except PackageNotFoundError:
        return "unknown"


def source_fingerprint(video: Path, chunk_size: int = 1024 * 1024) -> dict[str, Any]:
    video = video.resolve()
    if not video.is_file():
        raise FileNotFoundError(f"video not found: {video}")

    digest = hashlib.sha256()
    with video.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    stat = video.stat()
    return {
        "path": str(video),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": digest.hexdigest(),
    }


def transcript_path(video: Path, edit_dir: Path) -> Path:
    return edit_dir.resolve() / "transcripts" / f"{video.stem}.json"


def inspect_cache(
    out_path: Path,
    fingerprint: dict[str, Any],
    model: str = DEFAULT_MODEL,
) -> str:
    if not out_path.exists():
        return "missing"
    try:
        payload = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid"

    if not isinstance(payload, dict) or "source" not in payload or "engine" not in payload:
        return "legacy"
    expected = (
        payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("engine") == ENGINE
        and payload.get("language_code") == LANGUAGE_CODE
        and payload.get("model") == model
        and payload.get("source", {}).get("sha256") == fingerprint["sha256"]
    )
    return "valid" if expected else "stale"


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def adapt_words(segments: Iterable[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for segment in segments:
        for word in _value(segment, "words", None) or []:
            text = str(_value(word, "word", "")).strip()
            start = _value(word, "start")
            end = _value(word, "end")
            if not text or start is None or end is None:
                continue
            entry: dict[str, Any] = {
                "text": text,
                "start": round(float(start), 3),
                "end": round(float(end), 3),
                "type": "word",
                "speaker_id": None,
            }
            probability = _value(word, "probability")
            if probability is not None:
                entry["probability"] = round(float(probability), 6)
            result.append(entry)
    return result


def build_transcript_payload(
    segments: Iterable[Any],
    fingerprint: dict[str, Any],
    model: str,
    engine_version: str,
) -> dict[str, Any]:
    materialized = list(segments)
    words = adapt_words(materialized)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "text": " ".join(word["text"] for word in words),
        "language_code": LANGUAGE_CODE,
        "engine_language": ENGINE_LANGUAGE,
        "engine": ENGINE,
        "engine_version": engine_version or "unknown",
        "model": model,
        "source": fingerprint,
        "words": words,
    }
    validate_transcript_payload(payload)
    return payload


def validate_transcript_payload(payload: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "text",
        "language_code",
        "engine_language",
        "engine",
        "engine_version",
        "model",
        "source",
        "words",
    }
    missing = required.difference(payload)
    if missing:
        raise ValueError(
            f"transcript is missing required fields: {', '.join(sorted(missing))}"
        )
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported transcript schema version")
    if (
        payload["language_code"] != LANGUAGE_CODE
        or payload["engine_language"] != ENGINE_LANGUAGE
    ):
        raise ValueError("transcript language must be PT-BR")
    source = payload["source"]
    if not isinstance(source, dict) or len(str(source.get("sha256", ""))) != 64:
        raise ValueError("transcript source fingerprint is invalid")

    previous_start = -1.0
    for word in payload["words"]:
        text = word.get("text")
        start = word.get("start")
        end = word.get("end")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("transcript word text cannot be empty")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError("transcript word timestamps must be numeric")
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end < start
        ):
            raise ValueError("transcript word timestamps are invalid")
        if start < previous_start:
            raise ValueError("transcript words must be ordered by start time")
        if word.get("type") != "word" or word.get("speaker_id") is not None:
            raise ValueError(
                "local transcript words must use type=word and speaker_id=null"
            )
        probability = word.get("probability")
        if probability is not None and not 0 <= probability <= 1:
            raise ValueError(
                "transcript word probability must be between 0 and 1"
            )
        previous_start = float(start)


def atomic_write_json(out_path: Path, payload: dict[str, Any]) -> None:
    validate_transcript_payload(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=out_path.parent,
            prefix=f".{out_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            json.dump(payload, temp, ensure_ascii=False, indent=2)
            temp.write("\n")
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_path, out_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


class LocalTranscriber:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        model_dir: Path | None = None,
        device: str = "auto",
        compute_type: str = "auto",
        num_workers: int = 1,
    ) -> None:
        self.model_name = validate_model_name(model)
        self.model_dir = resolve_model_dir(self.model_name, model_dir)
        validate_model_dir(self.model_dir, self.model_name)
        if num_workers < 1:
            raise ValueError("worker count must be at least 1")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed; run: python -m pip install -e ."
            ) from exc

        try:
            self.model = WhisperModel(
                str(self.model_dir),
                device=device,
                compute_type=compute_type,
                num_workers=num_workers,
                local_files_only=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"failed to load local PT-BR model at {self.model_dir}: {exc}"
            ) from exc
        self.engine_version = package_version()

    def transcribe(
        self,
        video: Path,
        fingerprint: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            segments, _info = self.model.transcribe(
                str(video),
                language=ENGINE_LANGUAGE,
                task="transcribe",
                word_timestamps=True,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            return build_transcript_payload(
                list(segments),
                fingerprint,
                self.model_name,
                self.engine_version,
            )
        except Exception as exc:
            raise RuntimeError(f"local PT-BR transcription failed for {video.name}: {exc}") from exc


def transcribe_one(
    video: Path,
    edit_dir: Path,
    runtime: LocalTranscriber | None = None,
    model: str = DEFAULT_MODEL,
    model_dir: Path | None = None,
    device: str = "auto",
    compute_type: str = "auto",
    force: bool = False,
    verbose: bool = True,
    fingerprint: dict[str, Any] | None = None,
) -> Path:
    video = video.resolve()
    if not video.is_file():
        raise FileNotFoundError(f"video not found: {video}")
    model = validate_model_name(model)
    out_path = transcript_path(video, edit_dir)
    if not out_path.exists() and runtime is None:
        runtime = LocalTranscriber(
            model=model,
            model_dir=model_dir,
            device=device,
            compute_type=compute_type,
        )
    fingerprint = fingerprint or source_fingerprint(video)
    state = inspect_cache(out_path, fingerprint, model)
    if state == "valid" and not force:
        if verbose:
            print(f"cached: {out_path.name}")
        return out_path

    if verbose:
        reason = "forced" if force and out_path.exists() else state
        print(f"  transcribing {video.name} locally in PT-BR ({reason})", flush=True)
    started = time.monotonic()
    runtime = runtime or LocalTranscriber(
        model=model, model_dir=model_dir, device=device, compute_type=compute_type
    )
    payload = runtime.transcribe(video, fingerprint)
    atomic_write_json(out_path, payload)
    if verbose:
        elapsed = time.monotonic() - started
        print(
            f"  saved: {out_path.name} ({len(payload['words'])} words) "
            f"in {elapsed:.1f}s"
        )
    return out_path


class PTBRArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, f"{self.prog}: local PT-BR only: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = PTBRArgumentParser(
        description="Transcribe one video locally in PT-BR"
    )
    parser.add_argument("video", type=Path, help="Path to the PT-BR source video")
    parser.add_argument("--edit-dir", type=Path, default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--compute-type", default="auto")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    video = args.video.resolve()
    edit_dir = (args.edit_dir or (video.parent / "edit")).resolve()
    try:
        transcribe_one(
            video,
            edit_dir,
            model=args.model,
            model_dir=args.model_dir,
            device=args.device,
            compute_type=args.compute_type,
            force=args.force,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
