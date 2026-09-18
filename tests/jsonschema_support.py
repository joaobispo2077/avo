"""JSON Schema validators that resolve AVO's local $ref files."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from avo.paths import repo_root, schemas_dir


def schema_registry(root: Path | None = None) -> Registry:
    root = repo_root(root) if root is not None else None
    directory = schemas_dir() if root is None else root / "schemas"
    registry = Registry()
    paths = list(directory.glob("*.json"))
    provider = (root or repo_root()) / "providers" / "avo.provider.schema.json"
    if provider.is_file():
        paths.append(provider)
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(data)
        registry = registry.with_resource(path.name, resource)
        ident = data.get("$id")
        if isinstance(ident, str) and ident:
            registry = registry.with_resource(ident, resource)
    return registry


def validator_for(schema: dict, *, root: Path | None = None) -> Draft202012Validator:
    return Draft202012Validator(schema, registry=schema_registry(root))
