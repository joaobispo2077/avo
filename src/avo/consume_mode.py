"""Resolve checkout vs binary vs explicit override (spec FR-5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ORCHESTRATOR_MARK = "<!-- avo:orchestrator:start -->"


@dataclass(frozen=True)
class ConsumeMode:
    mode: str
    command_prefix: str | Path


def resolve_consume_mode(
    cwd: Path,
    override: str | None = None,
    *,
    home: Path,
) -> ConsumeMode:
    if override in ("mcp", "self-build"):
        prefix = "python -m avo.mcp" if override == "mcp" else "python -m"
        return ConsumeMode("override", prefix)
    if _is_avo_checkout(cwd):
        return ConsumeMode("checkout", "python -m")
    return ConsumeMode("binary", home / ".avo" / "bin" / "avo")


def _is_avo_checkout(cwd: Path) -> bool:
    pyproject = cwd / "pyproject.toml"
    agents = cwd / "AGENTS.md"
    if not pyproject.is_file() or not (cwd / "src" / "avo").is_dir() or not agents.is_file():
        return False
    try:
        named_avo = 'name = "avo"' in pyproject.read_text(encoding="utf-8")
        marked = ORCHESTRATOR_MARK in agents.read_text(encoding="utf-8")
    except OSError:
        return False
    return named_avo and marked
