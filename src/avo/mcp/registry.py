"""Canonical MCP tool metadata for avo.mcp.

Full phase-1 CLI groups are bridged (tasks 007–008). This module holds the
catalog model, meta-tool entries, and group tags for capability discovery.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Phase-1 transport identity (health / smoke).
TRANSPORT = "stdio"

# MCP protocol posture advertised by avo_health / avo_list_capabilities (FR-14, NFR-9).
# Exact shape is implementer-owned; must stay secret-free and project-free.
PROTOCOL_TARGET = "2026-07-28"
PROTOCOL_STATELESS = True
PROTOCOL_MRTR = True


def protocol_posture() -> dict[str, bool | str]:
    """Return the protocol posture object for health/capabilities payloads."""
    return {
        "target": PROTOCOL_TARGET,
        "stateless": PROTOCOL_STATELESS,
        "mrtr": PROTOCOL_MRTR,
    }


# Full phase-1 CLI groups (all bridged).
PLANNED_CLI_GROUPS: tuple[str, ...] = (
    "pipeline",
    "timeline",
    "sync",
    "animation",
    "tracks",
    "bmap",
    "cmap",
    "review",
    "deliver",
    "migrate-timeline",
    "cleanup",
)


@dataclass(frozen=True)
class ToolSpec:
    """Metadata for one MCP tool (registry entry; not the SDK binding)."""

    name: str
    description: str
    group: str
    destructive: bool = False
    cli_argv_template: tuple[str, ...] = field(default_factory=tuple)


META_HEALTH = ToolSpec(
    name="avo_health",
    description=(
        "Smoke check for avo.mcp identity/version/transport and protocol "
        "posture (MCP 2026-07-28, stateless, MRTR). Does not require --project."
    ),
    group="meta",
)

META_CAPABILITIES = ToolSpec(
    name="avo_list_capabilities",
    description=(
        "List registered avo.mcp tools with groups, descriptions, destructive/"
        "MRTR-gated notes, and docs pointers (FR-13 discovery folded here). "
        "Does not require --project."
    ),
    group="meta",
)


def meta_tool_specs() -> list[ToolSpec]:
    """Return phase-1 meta tool specs (health + capabilities)."""
    return [META_HEALTH, META_CAPABILITIES]


def cli_tool_specs() -> list[ToolSpec]:
    """Return all bridged CLI tool specs (core + remaining groups)."""
    # Lazy import avoids a circular import at package load (cli_tools → registry).
    from avo.mcp.tools.cli_tools import all_cli_tool_specs

    return all_cli_tool_specs()


def build_registry(extra: list[ToolSpec] | None = None) -> list[ToolSpec]:
    """Build the ordered tool catalog (meta first, then CLI tools, then extras)."""
    tools = list(meta_tool_specs())
    tools.extend(cli_tool_specs())
    if extra:
        tools.extend(extra)
    return tools


def tool_names(registry: list[ToolSpec] | None = None) -> list[str]:
    """Return tool names from a registry (default: current catalog)."""
    specs = registry if registry is not None else build_registry()
    return [spec.name for spec in specs]


def get_tool(name: str, registry: list[ToolSpec] | None = None) -> ToolSpec | None:
    """Look up a tool by exact name, or None if missing."""
    specs = registry if registry is not None else build_registry()
    for spec in specs:
        if spec.name == name:
            return spec
    return None


def tools_by_group(
    group: str,
    registry: list[ToolSpec] | None = None,
) -> list[ToolSpec]:
    """Return tools belonging to ``group`` (exact match)."""
    specs = registry if registry is not None else build_registry()
    return [spec for spec in specs if spec.group == group]


def registered_groups(registry: list[ToolSpec] | None = None) -> list[str]:
    """Return ordered unique group tags present in the registry."""
    specs = registry if registry is not None else build_registry()
    seen: list[str] = []
    for spec in specs:
        if spec.group not in seen:
            seen.append(spec.group)
    return seen
