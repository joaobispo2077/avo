"""Meta tools: health and capability discovery (no project required).

Docs discovery (FR-13) is folded into ``avo_list_capabilities`` via a docs
pointer — no separate ``avo_docs`` tool in phase-1 (per plan open question #3).
"""
from __future__ import annotations

from typing import Any

from avo.mcp import DOCS_POINTER, SERVER_NAME, package_version
from avo.mcp.registry import (
    META_CAPABILITIES,
    META_HEALTH,
    PLANNED_CLI_GROUPS,
    TRANSPORT,
    ToolSpec,
    build_registry,
    protocol_posture,
    registered_groups,
)


def health_payload() -> dict[str, Any]:
    """Return the ``avo_health`` success payload (no ``--project`` required).

    Includes protocol posture (FR-14 / NFR-9): target version, stateless, MRTR.
    Never includes secrets or project/provider paths.
    """
    return {
        "ok": True,
        "name": SERVER_NAME,
        "version": package_version(),
        "transport": TRANSPORT,
        "protocol": protocol_posture(),
    }


def capabilities_payload(
    *,
    group: str | None = None,
    registry: list[ToolSpec] | None = None,
) -> dict[str, Any]:
    """Return capability listing for registered tools (+ docs pointer).

    Docs discovery is included here (``docs`` field) rather than a dedicated
    tool — see plan recommendation for FR-13. Destructive tools are marked
    ``mrtr_gated: true`` so clients can see MRTR confirmation is expected.
    """
    catalog = registry if registry is not None else build_registry()
    specs = catalog
    if group:
        specs = [spec for spec in specs if spec.group == group]
    tools: list[dict[str, Any]] = []
    for spec in specs:
        entry: dict[str, Any] = {
            "name": spec.name,
            "description": spec.description,
            "group": spec.group,
            "destructive": spec.destructive,
        }
        # Additive MRTR note: registry destructive tools go through MRTR gates.
        if spec.destructive:
            entry["mrtr_gated"] = True
        tools.append(entry)
    return {
        "ok": True,
        "name": SERVER_NAME,
        "version": package_version(),
        "transport": TRANSPORT,
        "protocol": protocol_posture(),
        "docs": DOCS_POINTER,
        "groups": registered_groups(specs if group else catalog),
        "planned_cli_groups": list(PLANNED_CLI_GROUPS),
        "tools": tools,
    }


def register_meta_tools(server: Any, *, registry: list[ToolSpec] | None = None) -> None:
    """Register meta tools on an ``MCPServer`` instance.

    ``server`` is typed as Any so importing this module does not require the
    optional ``mcp`` SDK (unit tests can call payload helpers without it).
    """
    catalog = registry if registry is not None else build_registry()

    @server.tool(
        name=META_HEALTH.name,
        description=META_HEALTH.description,
    )
    def avo_health() -> dict[str, Any]:
        return health_payload()

    @server.tool(
        name=META_CAPABILITIES.name,
        description=META_CAPABILITIES.description,
    )
    def avo_list_capabilities(group: str | None = None) -> dict[str, Any]:
        return capabilities_payload(group=group, registry=catalog)

    # Keep references so linters do not treat registrations as unused.
    _ = (avo_health, avo_list_capabilities)
