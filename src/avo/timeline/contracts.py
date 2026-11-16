"""Strict JSON contracts and deterministic identity for timeline artifacts."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any

from avo.paths import schema_path


class ContractError(ValueError):
    """Raised when a canonical timeline document violates its contract."""


_FINGERPRINT_STAGE: ContextVar[dict | None] = ContextVar(
    "fingerprint_stage", default=None
)


@contextmanager
def fingerprint_stage(*, reuse_current=False, verify_on_exit=False):
    """Cache an immutable stage, optionally sharing it and freshly checking its end."""
    current = _FINGERPRINT_STAGE.get()
    observations = current if reuse_current and current is not None else {}
    token = _FINGERPRINT_STAGE.set(observations)
    try:
        yield observations
        if verify_on_exit:
            expected = {key[0]: value for key, value in observations.items()}
            # A fresh nested stage deliberately ignores the shared stat cache.
            with fingerprint_stage():
                for value in expected.values():
                    try:
                        actual = file_fingerprint(Path(value["locator"]))
                    except OSError as exc:
                        raise ContractError(
                            f"file changed during fingerprint stage: {value['locator']}"
                        ) from exc
                    if any(
                        actual[key] != value[key] for key in ("sha256", "sizeBytes")
                    ):
                        raise ContractError(
                            f"file changed during fingerprint stage: {value['locator']}"
                        )
    finally:
        _FINGERPRINT_STAGE.reset(token)


def _fingerprint_key(path):
    stat = path.stat()
    return (
        str(path.resolve()),
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        stat.st_dev,
        stat.st_ino,
    )


def canonical_json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(f"value is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_fingerprint(path: Path) -> dict[str, Any]:
    path = Path(path)
    observations = _FINGERPRINT_STAGE.get()
    key = _fingerprint_key(path) if observations is not None else None
    if observations is not None and key in observations:
        return {**observations[key], "locator": str(path)}
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    result = {"sha256": digest.hexdigest(), "sizeBytes": size, "locator": str(path)}
    if observations is not None:
        _remember_fingerprint(observations, key, result, path)
    return result


def _remember_fingerprint(observations, key, result, path):
    if _fingerprint_key(path) != key:
        raise ContractError(f"media changed while fingerprinting: {path}")
    for previous_key, previous in observations.items():
        if previous_key[0] == key[0] and any(
            previous[field] != result[field] for field in ("sha256", "sizeBytes")
        ):
            raise ContractError(f"file changed within fingerprint stage: {path}")
    observations[key] = dict(result)


def _schema_location(name: str, root: Path | None = None) -> tuple[Path, str]:
    # An existing literal filename wins over interpreting its hashes as fragments.
    offsets = [len(name), *(index for index, value in enumerate(name) if value == "#")]
    for offset in offsets:
        filename, fragment = name[:offset], name[offset + 1 :]
        path = (Path(root) / filename) if root else schema_path(filename)
        if path.is_file():
            return path, fragment
    filename, _, fragment = name.partition("#")
    return (Path(root) / filename) if root else schema_path(filename), fragment


def _schema_and_fragment(
    name: str, root: Path | None = None
) -> tuple[dict[str, Any], str]:
    path, fragment = _schema_location(name, root)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"cannot load schema {path}: {exc}") from exc
    return schema, fragment


def _schema_registry(root: Path):
    """Build a local registry so production schemas may use cross-file refs."""
    try:
        from referencing import Registry, Resource
    except ImportError as exc:  # pragma: no cover - jsonschema installs referencing
        raise ContractError(f"cannot load JSON Schema registry support: {exc}") from exc

    registry = Registry()
    for path in sorted(Path(root).glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # An unrelated optional schema must not break validation of a
            # self-contained contract. A referenced malformed schema remains
            # absent and therefore fails closed when the validator resolves it.
            continue
        identifier = document.get("$id") if isinstance(document, dict) else None
        if identifier:
            registry = registry.with_resource(
                str(identifier), Resource.from_contents(document)
            )
    return registry


def load_schema(name: str, root: Path | None = None) -> dict[str, Any]:
    schema, fragment = _schema_and_fragment(name, root)
    if not fragment:
        return schema
    node: Any = schema
    for token in fragment.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            raise ContractError(f"schema fragment not found: #{fragment}")
        node = node[token]
    result = {
        "$schema": schema.get("$schema"),
        "$defs": schema.get("$defs", {}),
        **node,
    }
    if schema.get("$id"):
        result["$id"] = schema["$id"]
    return result


@lru_cache(maxsize=32)
def _checked_validator(schema_bytes: bytes):
    """Cache schema checking by complete content, never by file metadata or input."""
    import jsonschema

    schema = json.loads(schema_bytes)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls


def validate_document(
    document: Any,
    schema_name: str,
    *,
    root: Path | None = None,
) -> Any:
    schema = load_schema(schema_name, root)
    schema_root = Path(root) if root else _schema_location(schema_name)[0].parent
    try:
        validator_cls = _checked_validator(canonical_json_bytes(schema))
        errors = sorted(
            validator_cls(schema, registry=_schema_registry(schema_root)).iter_errors(
                document
            ),
            key=lambda error: list(error.absolute_path),
        )
    except Exception as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError(f"schema validation failed to run: {exc}") from exc
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ContractError(details)
    return document


def validate_proof_plan_document(document):
    """Read legacy and camera-aware plans explicitly; unknown versions fail closed."""
    if not isinstance(document, dict):
        raise ContractError("proof plan must be an object")
    version = document.get("schemaVersion")
    if not isinstance(version, str):
        raise ContractError("unsupported proof plan contract version")
    schema = {
        "1.0.0": "avo.proof-plan.schema.json",
        "2.0.0": "avo.proof-plan.v2.schema.json",
    }.get(version)
    if schema is None:
        raise ContractError("unsupported proof plan contract version")
    validate_document(document, schema)
    if version == "1.0.0" and any(
        operation["kind"] == "camera-transform"
        for operation in document["videoGraph"]["operations"]
    ):
        raise ContractError("camera operations require proof plan contract 2.0.0")
    return document


def _has_editing_craft(snapshot):
    components = snapshot.get("components")
    if not isinstance(components, list):
        return False
    return any(
        isinstance(component, dict)
        and isinstance(component.get("extensions"), dict)
        and "editingCraft" in component["extensions"]
        for component in components
    )


def required_animation_readers(snapshot: dict[str, Any]) -> tuple[str, ...]:
    """Validate advanced intent even when a generic revision writer receives it."""
    if "strategyContractVersion" not in snapshot and not _has_editing_craft(snapshot):
        return ()
    if snapshot.get("strategyContractVersion") != "2.0.0":
        raise ContractError("advanced camera strategy requires contract 2.0.0")
    validate_document(snapshot, "avo.animation.schema.json#/$defs/videoStrategy")
    return ("animation-strategy-v2", "camera-behavior-v1")


def require_animation_reader(index: dict[str, Any], snapshot: dict[str, Any]) -> None:
    """An advanced snapshot is unreadable without its atomic index capability fence."""
    required = set(required_animation_readers(snapshot))
    if required and (
        index["artifactType"] != "animation"
        or index["schemaVersion"] != "2.0.0"
        or not required.issubset(index.get("requiredReaderCapabilities", []))
    ):
        raise ContractError(
            "camera strategy requires its versioned index reader capabilities"
        )


def dependency_lock_hash(dependencies: dict[str, str]) -> str:
    """Hash a sorted exact dependency map after strict SHA-256 validation."""
    import re

    normalized: dict[str, str] = {}
    for key, value in sorted(dependencies.items()):
        if not re.fullmatch(r"[a-f0-9]{64}", str(value)):
            raise ContractError(f"dependency {key!r} is not an exact sha256")
        normalized[str(key)] = str(value)
    if not normalized:
        raise ContractError("dependency lock cannot be empty")
    return content_hash(normalized)


def document_hash_excluding(document: dict[str, Any], field: str) -> str:
    return content_hash({key: value for key, value in document.items() if key != field})
