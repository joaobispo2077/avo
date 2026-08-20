"""Stdio MCP server for AVO.

Uses the official ``mcp`` Python SDK ``MCPServer`` API (SDK v2+; ``FastMCP`` was
removed from ``mcp.server.fastmcp``). Install with::

    pip install 'avo[mcp]'

Stdout is reserved for MCP framing — log only to stderr.

Client capabilities declared at initialize (elicitation / sampling / roots)
flow through MCP ``Context.client_capabilities`` into MRTR gating for
destructive tools — see :mod:`avo.mcp.mrtr`.
"""

from __future__ import annotations

import sys
from typing import Any

from avo.mcp import SERVER_NAME, package_version
from avo.mcp.registry import build_registry
from avo.mcp.tools.cli_tools import register_cli_tools
from avo.mcp.tools.meta import register_meta_tools

_MISSING_MCP_MSG = (
    "avo.mcp requires the optional 'mcp' package.\n"
    "Install with: pip install 'avo[mcp]'\n"
    "Or: pip install 'mcp>=1.28'"
)


def _require_mcp() -> Any:
    """Import ``MCPServer`` or exit with a clear stderr install hint."""
    try:
        from mcp.server import MCPServer
    except ImportError:
        print(_MISSING_MCP_MSG, file=sys.stderr)
        raise SystemExit(1) from None
    return MCPServer


def create_server() -> Any:
    """Build an ``MCPServer`` with meta + all CLI-bridged tools registered."""
    MCPServer = _require_mcp()
    registry = build_registry()
    server = MCPServer(
        name=SERVER_NAME,
        version=package_version(),
        instructions=(
            "AVO orchestrator MCP adapter (local stdio). "
            "Additive to skills and avo CLI — not an editor/NLE MCP. "
            "Use avo_health to smoke-test; avo_list_capabilities to discover tools "
            "(includes docs pointers). "
            "Destructive tools use MRTR InputRequiredResult and require client "
            "elicitation/create (form) — unsupported input methods are never requested; "
            "confirmation is never faked when elicitation is absent."
        ),
    )
    register_meta_tools(server, registry=registry)
    register_cli_tools(server)  # all phase-1 CLI groups (tasks 007–008)
    return server


def run_stdio() -> None:
    """Start the MCP server on stdio (blocking). Logs only to stderr."""
    # Keep any library logging off stdout so MCP framing stays intact.
    import logging

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    server = create_server()
    # MCPServer.run(transport="stdio") is the SDK v2 sync entry for stdio.
    server.run(transport="stdio")
