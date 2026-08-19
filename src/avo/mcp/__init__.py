"""Local stdio MCP adapter for AVO (`avo.mcp`).

Additive harness surface over ``avo.cli`` — does not replace skills or the CLI.
Phase-1 transport is stdio only; install the optional extra with ``pip install 'avo[mcp]'``.

This package must not print to stdout at import time (stdout is reserved for MCP framing).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

SERVER_NAME = "avo.mcp"
DOCS_POINTER = "docs/avo-mcp.md"


def package_version() -> str:
    """Return the installed ``avo`` distribution version, or a safe fallback."""
    try:
        return version("avo")
    except PackageNotFoundError:
        return "0.0.0+local"


__all__ = ["DOCS_POINTER", "SERVER_NAME", "package_version"]
