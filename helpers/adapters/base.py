"""Shared port protocol and routing resolution from avo.config.json."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class AdapterError(Exception):
    """Configuration or adapter resolution failure."""


@dataclass
class JobRequest:
    job: str
    label: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    root: Path = field(default_factory=Path.cwd)


@dataclass
class JobResult:
    exit_code: int
    artifact_paths: list[Path] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    models_used: dict[str, str] = field(default_factory=dict)


class JobAdapter(Protocol):
    routing_id: str

    def run(self, request: JobRequest) -> JobResult: ...


def repo_root(start: Path | None = None) -> Path:
    if start is not None:
        return start.resolve()
    return Path(__file__).resolve().parent.parent.parent


def load_routing_config(root: Path) -> dict[str, Any]:
    path = root / "avo.config.json"
    if not path.is_file():
        raise AdapterError(f"missing routing config: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_routing_token(token: str) -> tuple[str, str]:
    token = token.strip()
    if "+" in token:
        owner, suffix = token.split("+", 1)
        return owner.strip(), suffix.strip()
    return token, token


def routing_token_for_job(config: dict[str, Any], job: str, label: str) -> str:
    jobs = config.get("jobs") or {}
    if job not in jobs:
        raise AdapterError(f"unknown job '{job}' in avo.config.json")
    job_spec = jobs[job]
    if label not in job_spec:
        raise AdapterError(f"job '{job}' has no label '{label}' in avo.config.json")
    value = job_spec[label]
    if isinstance(value, list):
        if not value:
            raise AdapterError(f"job '{job}' label '{label}' is an empty list")
        value = value[0]
    if not isinstance(value, str):
        raise AdapterError(f"job '{job}' label '{label}' must be a string or list")
    return value


def resolve_adapter(job: str, label: str, root: Path | None = None) -> JobAdapter:
    from helpers.adapters.registry import adapter_for_routing_suffix

    root = repo_root(root)
    config = load_routing_config(root)
    token = routing_token_for_job(config, job, label)
    _owner, suffix = parse_routing_token(token)
    adapter_cls = adapter_for_routing_suffix(job, suffix)
    return adapter_cls()


def load_adapter_class(module_path: str) -> type[JobAdapter]:
    module_name, _, class_name = module_path.partition(":")
    if not class_name:
        raise AdapterError(f"invalid adapter path: {module_path}")
    module = importlib.import_module(module_name)
    adapter_cls = getattr(module, class_name)
    return adapter_cls
