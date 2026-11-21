"""Verify explicitly provisioned embedding artifacts without loading a model."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from avo.timeline.contracts import content_hash, file_fingerprint, validate_document

JSON_LIMIT = 1024 * 1024


class EmbeddingError(ValueError):
    """An optional embedding request cannot be executed faithfully."""


def read_bounded_json(path, *, limit=JSON_LIMIT, expected_sha256=None):
    with Path(path).open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise EmbeddingError("embedding JSON exceeds its byte budget")
    if (
        expected_sha256 is not None
        and hashlib.sha256(data).hexdigest() != expected_sha256
    ):
        raise EmbeddingError("embedding manifest digest mismatch")
    try:
        return json.loads(
            data, object_pairs_hook=_unique_pairs, parse_constant=_bad_number
        )
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise EmbeddingError("invalid embedding JSON") from exc


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise EmbeddingError("duplicate embedding JSON key")
        value[key] = item
    return value


def _bad_number(_value):
    raise EmbeddingError("non-finite embedding JSON number")


def contained_file(root, relative):
    locator = Path(str(relative))
    if locator.is_absolute() or ".." in locator.parts or "\\" in str(relative):
        raise EmbeddingError("embedding artifact path escapes its declared root")
    path = (root / locator).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise EmbeddingError("embedding artifact is missing or escapes its root")
    return path


def _offline_runtime(runtime):
    if (
        runtime.get("offline") is not True
        or runtime.get("allowDownload", False) is not False
    ):
        raise EmbeddingError(
            "embedding execution requires offline mode and no downloads"
        )
    if runtime.get("device", "cpu") not in {"cpu", "cuda"} or runtime.get(
        "computeType", "float32"
    ) not in {"auto", "float32"}:
        raise EmbeddingError(
            "CLAP requires an explicitly supported CPU/CUDA float32 runtime"
        )


def _local_source(resolved):
    source = resolved.pin.get("source") or {}
    runtime = resolved.pin.get("runtime") or {}
    _offline_runtime(runtime)
    if source.get("kind") != "artifact" or not source.get("manifestPath"):
        raise EmbeddingError("a pinned local embedding manifest must be provisioned")
    directory = Path(source.get("artifactPath", "")).resolve()
    manifest_path = Path(source["manifestPath"]).resolve()
    if not directory.is_dir() or not manifest_path.is_relative_to(directory):
        raise EmbeddingError("embedding manifest must be inside its local model root")
    return source, runtime, directory, manifest_path


def _checked_manifest(resolved):
    source, runtime, directory, manifest_path = _local_source(resolved)
    expected = source.get("manifestSha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise EmbeddingError("embedding manifest digest must be pinned")
    document = read_bounded_json(manifest_path, expected_sha256=expected)
    try:
        validate_document(document, "avo.clap-manifest.schema.json")
    except ValueError as exc:
        raise EmbeddingError(f"invalid embedding manifest: {exc}") from exc
    return document, directory, runtime


def _verify_loader_inventory(document, directory, manifest_path):
    # Static CLAP still discovers tokenizer/config files; every consumed file is pinned.
    for index, path in enumerate(directory.rglob("*")):
        if index >= 256:
            raise EmbeddingError("embedding model inventory exceeds its file budget")
        if path == manifest_path or path.suffix not in {
            ".json",
            ".txt",
            ".bin",
            ".safetensors",
        }:
            continue
        if (
            path.is_file()
            and path.relative_to(directory).as_posix() not in document["files"]
        ):
            raise EmbeddingError(
                "unlisted embedding loader artifact is not digest-pinned"
            )


def _verify_files(document, directory):
    files = document["files"]
    required = {
        "config.json",
        "preprocessor_config.json",
        "tokenizer.json",
        document["license"]["noticeFile"],
        document["runtime"]["lockFile"],
    }
    if not required.issubset(files) or not {
        "model.safetensors",
        "pytorch_model.bin",
    }.intersection(files):
        raise EmbeddingError(
            "embedding model, processor, license and runtime lock files are required"
        )
    for relative, expected in files.items():
        path = contained_file(directory, relative)
        limit = 8 * 1024**3 if path.suffix in {".bin", ".safetensors"} else 8 * 1024**2
        if path.stat().st_size > limit:
            raise EmbeddingError("embedding artifact exceeds its byte budget")
        if file_fingerprint(path)["sha256"] != expected:
            raise EmbeddingError(f"embedding artifact digest mismatch: {relative}")
    config = read_bounded_json(directory / "config.json")
    processor = read_bounded_json(directory / "preprocessor_config.json")
    if (
        config.get("model_type") != "clap"
        or config.get("projection_dim") != document["dimension"]
    ):
        raise EmbeddingError(
            "embedding model type or dimension differs from the manifest"
        )
    if processor.get("sampling_rate") != document["preprocessing"]["sampleRate"]:
        raise EmbeddingError(
            "embedding processor sample rate differs from the manifest"
        )


def _verified_executables(document, runtime):
    result = {}
    for key, digest in (("pythonEnv", "pythonSha256"), ("ffmpegPath", "ffmpegSha256")):
        path = Path(runtime.get(key) or "").resolve()
        if not path.is_file() or path.stat().st_size > 512 * 1024**2:
            raise EmbeddingError(
                f"embedding executable missing or exceeds budget: {key}"
            )
        if file_fingerprint(path)["sha256"] != document["runtime"][digest]:
            raise EmbeddingError(f"embedding executable digest mismatch: {key}")
        result[key] = path
    return result


def load_embedding_manifest(resolved):
    try:
        document, directory, runtime = _checked_manifest(resolved)
        _verify_loader_inventory(
            document, directory, Path(resolved.pin["source"]["manifestPath"]).resolve()
        )
        _verify_files(document, directory)
        executables = _verified_executables(document, runtime)
        worker = (
            Path(__file__).parent
            / "adapters"
            / "understand"
            / "clap_embeddings_worker.py"
        )
        identity = {
            "dimension": document["dimension"],
            "normalization": "l2",
            "modelDigest": content_hash(
                {
                    key: document[key]
                    for key in ("modelId", "revision", "files", "license")
                }
            ),
            "preprocessingDigest": content_hash(
                {
                    "parameters": document["preprocessing"],
                    "implementationSha256": file_fingerprint(worker)["sha256"],
                }
            ),
            "runtimeDigest": content_hash(document["runtime"]),
        }
        return {
            "document": document,
            "directory": directory,
            "python": executables["pythonEnv"],
            "ffmpeg": executables["ffmpegPath"],
            "runtime": runtime,
            "jointSpace": {"id": content_hash(identity), **identity},
        }
    except (OSError, KeyError, TypeError, RecursionError) as exc:
        raise EmbeddingError(f"embedding artifacts unavailable: {exc}") from exc


def validate_joint_space(value):
    fields = {
        "id",
        "dimension",
        "normalization",
        "modelDigest",
        "preprocessingDigest",
        "runtimeDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise EmbeddingError("joint-space identity is incomplete")
    if (
        type(value["dimension"]) is not int
        or not 2 <= value["dimension"] <= 4096
        or value["normalization"] != "l2"
    ):
        raise EmbeddingError("joint-space dimension or normalization is unsupported")
    _identity_digest(value, fields)
    return value


def _identity_digest(value, fields):
    if any(
        not isinstance(value[key], str) or not re.fullmatch("[a-f0-9]{64}", value[key])
        for key in fields - {"dimension", "normalization"}
    ):
        raise EmbeddingError("joint-space identity requires exact digests")
    if value["id"] != content_hash(
        {key: item for key, item in value.items() if key != "id"}
    ):
        raise EmbeddingError("joint-space identity digest does not match its fields")
