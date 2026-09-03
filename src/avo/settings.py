"""Generic scoped-setting resolution with provenance and safe path handling."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SettingsError(ValueError):
    """Raised before work starts when a scoped setting is invalid."""


@dataclass(frozen=True)
class EffectiveSetting:
    value: Any
    source: str
    explicit: bool


@dataclass(frozen=True)
class ResolvedSettings:
    values: dict[str, Any]
    sources: dict[str, str]
    policy_hash: str

    def setting(self, path: str) -> EffectiveSetting:
        """Return one resolved value with its immutable provenance."""
        value: Any = self.values
        for token in path.split("."):
            if not isinstance(value, Mapping) or token not in value:
                raise SettingsError(f"unknown setting: {path}")
            value = value[token]
        source = self.sources.get(path, "default")
        return EffectiveSetting(
            value=value, source=source, explicit=source != "default"
        )

    def payload(self) -> dict[str, Any]:
        return {
            "effective": self.values,
            "sources": self.sources,
            "policyHash": self.policy_hash,
        }


def stable_settings_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _merge(
    target: dict[str, Any],
    sources: dict[str, str],
    patch: Mapping[str, Any],
    source: str,
    prefix: str = "",
) -> None:
    for key, value in patch.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping) and isinstance(target.get(key), Mapping):
            nested = dict(target[key])
            _merge(nested, sources, value, source, path)
            target[key] = nested
            continue
        target[key] = list(value) if isinstance(value, list) else value
        sources[path] = source
        if isinstance(value, Mapping):
            for nested_key in value:
                sources[f"{path}.{nested_key}"] = source


def resolve_scoped_settings(
    *,
    defaults: Mapping[str, Any],
    scopes: Iterable[tuple[str, Mapping[str, Any] | None]],
) -> ResolvedSettings:
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    _merge(values, sources, defaults, "default")
    for source, patch in scopes:
        if patch:
            _merge(values, sources, patch, source)
    return ResolvedSettings(
        values=values,
        sources=dict(sorted(sources.items())),
        policy_hash=stable_settings_hash(
            {"effective": values, "sources": dict(sorted(sources.items()))}
        ),
    )


def resolve_path_setting(
    value: str | Path,
    *,
    base: Path,
    contain: bool = True,
) -> Path:
    base = Path(base).expanduser().resolve()
    candidate = Path(value).expanduser()
    resolved = (candidate if candidate.is_absolute() else base / candidate).resolve()
    if contain:
        try:
            resolved.relative_to(base)
        except ValueError as error:
            raise SettingsError(
                f"configured path must remain inside rawDir: {value}"
            ) from error
    return resolved


def redact_path(value: str | Path | None, *, base: Path) -> str | None:
    if value is None:
        return None
    resolved = Path(value).expanduser().resolve()
    root = Path(base).expanduser().resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return f"<external>/{resolved.name}"
    suffix = relative.as_posix()
    return "<rawDir>" if not suffix else f"<rawDir>/{suffix}"
