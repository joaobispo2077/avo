"""Unit tests for avo.mcp package skeleton (no live stdio host required)."""
from __future__ import annotations

import importlib
import io
import sys
from contextlib import redirect_stdout

import pytest


def test_mcp_package_import_has_no_stdout() -> None:
    """Importing avo.mcp must not print to stdout (MCP framing hygiene)."""
    modules = [
        name
        for name in list(sys.modules)
        if name == "avo.mcp" or name.startswith("avo.mcp.")
    ]
    for name in modules:
        del sys.modules[name]

    buf = io.StringIO()
    with redirect_stdout(buf):
        import avo.mcp as mcp_pkg

        importlib.reload(mcp_pkg)

    assert buf.getvalue() == ""
    assert mcp_pkg.SERVER_NAME == "avo.mcp"
    assert isinstance(mcp_pkg.package_version(), str)


def test_bridge_run_cli_captures_stdout(tmp_path) -> None:
    """Bridge captures CLI stdout into the result envelope."""
    import json

    from avo.mcp.bridge import run_cli

    project = tmp_path / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "bishop",
                "videoId": "mcp-bridge",
                "rawDir": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    result = run_cli(["pipeline", "run", "--project", str(project)])
    assert result.ok is True
    assert result.exit_code == 0
    assert result.stdout.strip() != ""
    envelope = result.to_dict()
    assert envelope["ok"] is True
    assert "stdout" in envelope


def test_bridge_run_cli_argparse_failure_is_captured() -> None:
    from avo.mcp.bridge import run_cli

    result = run_cli(["pipeline"])  # missing required subcommand
    assert result.ok is False
    assert result.exit_code != 0


def test_create_server_registers_meta_and_all_cli_tools() -> None:
    pytest.importorskip("mcp")
    import asyncio

    from avo.mcp.server import create_server

    server = create_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert "avo_health" in names
    assert "avo_list_capabilities" in names
    assert "avo_pipeline_status" in names
    assert "avo_tracks_inspect" in names
    assert "avo_bmap_status" in names
    assert "avo_cleanup_execute" in names
    assert "avo_migrate_timeline_activate" in names
