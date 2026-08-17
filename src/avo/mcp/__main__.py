"""``python -m avo.mcp`` — start the local stdio MCP server."""
from __future__ import annotations

from avo.mcp.server import run_stdio


def main() -> None:
    run_stdio()


if __name__ == "__main__":
    main()
