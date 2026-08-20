"""CI-safe MCP integration smoke (in-process client; no providers/footage).

Uses the official ``mcp`` SDK ``Client`` against ``create_server()`` over the
in-memory transport (same tool registration as stdio). Does not spawn a
blocking ``run_stdio()`` child — avoids hanging CI.
"""

from __future__ import annotations

import asyncio
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.client import Client

from avo.mcp import DOCS_POINTER, SERVER_NAME, package_version
from avo.mcp.server import create_server

pytestmark = pytest.mark.integration


def _tool_payload(result) -> dict:
    """Extract JSON payload from a CallToolResult (structured or text content)."""
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None) or []
    if content:
        text = getattr(content[0], "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"tool result had no JSON payload: {result!r}")


def test_inprocess_mcp_initialize_list_health_and_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """initialize → list tools → avo_health / capabilities without project roots."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "providers").exists()

    async def _smoke() -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            server = create_server()
            async with Client(server) as client:
                info = client.server_info
                assert info is not None
                assert info.name == SERVER_NAME

                listed = await client.list_tools()
                names = {t.name for t in listed.tools}
                assert "avo_health" in names
                assert "avo_list_capabilities" in names
                assert "avo_pipeline_status" in names
                assert len(names) >= 2

                health_result = await client.call_tool("avo_health", {})
                assert getattr(health_result, "is_error", False) is False
                health = _tool_payload(health_result)
                assert health["ok"] is True
                assert health["name"] == SERVER_NAME
                assert health["version"] == package_version()
                assert health["transport"] == "stdio"
                assert "project" not in health
                assert "provider" not in health

                caps_result = await client.call_tool("avo_list_capabilities", {})
                assert getattr(caps_result, "is_error", False) is False
                caps = _tool_payload(caps_result)
                assert caps["ok"] is True
                assert caps["docs"] == DOCS_POINTER
                cap_names = {t["name"] for t in caps["tools"]}
                assert "avo_health" in cap_names
                assert "avo_list_capabilities" in cap_names
                # Capabilities catalog is the source of truth for registered tools.
                assert names == cap_names

        assert buf.getvalue() == "", "MCP smoke must not print to stdout"

    asyncio.run(_smoke())


def test_create_server_needs_no_providers_or_footage_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Building the server must not require providers/*, footage, or project env."""
    monkeypatch.chdir(tmp_path)
    for key in (
        "AVO_PROVIDER",
        "AVO_PROJECT",
        "AVO_RAW_DIR",
        "AVO_PROVIDERS_DIR",
    ):
        monkeypatch.delenv(key, raising=False)

    assert not (tmp_path / "providers").exists()
    server = create_server()
    assert server.name == SERVER_NAME
    assert server.version == package_version()


def test_stdio_entrypoint_is_wired_without_starting_loop() -> None:
    """``run_stdio`` exists and create_server is the stdio build path (no hang)."""
    from avo.mcp import server as mcp_server

    assert callable(mcp_server.run_stdio)
    assert callable(mcp_server.create_server)
    # Do not call run_stdio() here — it blocks on stdin forever.
