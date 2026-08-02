"""Canonical repository path resolution for the AVO orchestrator."""

from __future__ import annotations

import os
from pathlib import Path

_ENV_ROOT = "AVO_ROOT"


def repo_root(start: Path | None = None) -> Path:
    """Return the AVO repository root (directory containing pyproject.toml)."""
    if start is not None:
        return start.resolve()
    override = os.environ.get(_ENV_ROOT, "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        if path.is_dir():
            return path
    # src/avo/paths.py -> avo -> src -> repo root
    return Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    """Directory for orchestrator config manifests (config/ when relocated)."""
    nested = repo_root() / "config"
    if nested.is_dir():
        return nested
    return repo_root()


def config_path(name: str) -> Path:
    """Resolve a config manifest path, preferring config/ when present."""
    nested = repo_root() / "config" / name
    if nested.is_file():
        return nested
    return repo_root() / name


def schemas_dir() -> Path:
    """Directory for public JSON Schema contracts (schemas/ when relocated)."""
    nested = repo_root() / "schemas"
    if nested.is_dir():
        return nested
    return repo_root()


def schema_path(name: str) -> Path:
    """Resolve a schema file path, preferring schemas/ when present."""
    nested = repo_root() / "schemas" / name
    if nested.is_file():
        return nested
    legacy_specs = (
        repo_root()
        / "specs"
        / "002-edit-switch-save-video"
        / "contracts"
        / name
    )
    if legacy_specs.is_file():
        return legacy_specs
    return repo_root() / name


def providers_dir() -> Path:
    return repo_root() / "providers"


def assert_layout() -> None:
    """Raise FileNotFoundError when required orchestrator manifests are missing."""
    required = [
        config_path("avo.config.json"),
        config_path("avo.dependencies.json"),
        schema_path("avo.project.schema.json"),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "AVO orchestrator layout incomplete; missing: " + ", ".join(missing)
        )
