"""Same no-inference accounting surface through engine, CLI and optional MCP."""

import json

from avo import engine_cli
from avo.mcp.bridge import run_cli
from avo.mcp.registry import get_tool
from avo.paths import schema_path


def test_engine_capabilities_routes_to_same_command(capsys):
    assert engine_cli.main(["costs", "capabilities", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert engine_cli.main(["metrics", "capabilities", "--json"]) == 0
    assert first == json.loads(capsys.readouterr().out)


def test_mcp_reads_and_mutations_are_classified():
    assert not get_tool("avo_costs_report").destructive
    assert not get_tool("avo_costs_capabilities").destructive
    assert get_tool("avo_costs_import").destructive
    assert get_tool("avo_costs_bind").destructive
    assert get_tool("avo_costs_snapshot").destructive
    assert run_cli(["costs", "capabilities", "--json"]).parsed_json["agents"]


def test_shipped_schema_paths_exist():
    for kind in (
        "identity",
        "binding",
        "observation",
        "batch",
        "price",
        "correction",
        "snapshot",
    ):
        assert schema_path(f"avo.cost-{kind}.schema.json").is_file()
