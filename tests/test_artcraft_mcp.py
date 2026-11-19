import json

import pytest

from avo.mcp.bridge import run_bridged, run_cli
from tests.artcraft_fixtures import request


@pytest.mark.parametrize("action", ["assess", "catalog"])
def test_read_only_bridge_tools_are_discoverable_and_match_cli(action):
    from avo.mcp.tools.cli_tools import all_bridge_defs

    tools = [
        tool for tool in all_bridge_defs() if tool.spec.name == f"avo_artcraft_{action}"
    ]
    assert len(tools) == 1
    tool = tools[0]
    assert tool.cli_prefix == ("artcraft", action)
    assert tool.spec.destructive is False

    prefix = ["artcraft", action]
    params = {"as_json": True}
    arguments = [*prefix, "--json"]
    if action == "assess":
        brief = request(purpose='Show the label "Café" on both layouts.')
        params["request"] = brief
        arguments += ["--request-json", json.dumps(brief, ensure_ascii=False)]
    else:
        params["app"] = "effectcraft"
        arguments += ["--app", "effectcraft"]
    bridged = run_bridged(tool.cli_prefix, params)
    cli = run_cli(arguments)
    assert bridged.ok, bridged.stderr
    assert bridged.parsed_json == cli.parsed_json


def test_artcraft_mcp_does_not_treat_a_client_path_as_a_request():
    result = run_bridged(
        ("artcraft", "assess"), {"request": "client.json", "as_json": True}
    )
    assert not result.ok
    assert json.loads(result.stderr)["code"] == "ARTCRAFT_INVALID_REQUEST"
