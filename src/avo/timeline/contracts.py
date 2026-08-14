"""Strict JSON contracts and deterministic identity for timeline artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from avo.paths import schema_path


class ContractError(ValueError):
    """Raised when a canonical timeline document violates its contract."""


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
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "sizeBytes": size, "locator": str(path)}


def _schema_and_fragment(name: str, root: Path | None = None) -> tuple[dict[str, Any], str]:
    filename, separator, fragment = name.partition("#")
    path = (Path(root) / filename) if root else schema_path(filename)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"cannot load schema {path}: {exc}") from exc
    return schema, fragment if separator else ""


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


def validate_document(
    document: Any,
    schema_name: str,
    *,
    root: Path | None = None,
) -> Any:
    schema = load_schema(schema_name, root)
    try:
        import jsonschema
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        errors = sorted(
            validator_cls(schema).iter_errors(document),
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
