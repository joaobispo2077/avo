"""The shared transition service is exposed consistently through CLI and MCP."""

import json

from avo.cli import main
from avo.cost_participation import register_context
from avo.mcp.bridge import run_bridged
from avo.mcp.tools.cli_tools import all_bridge_defs
from test_cost_continuity import host_descriptor, production, transition_request


def _handoff(tmp_path):
    store, project = production(tmp_path)
    source = register_context(store, host_descriptor("first"))
    request = transition_request(
        store,
        source["participationId"],
        kind="boundary-unknown",
        boundary={"kind": "unknown"},
        declaration=host_descriptor("second", "claude"),
    )
    return store, project, request


def test_transition_cli_replays_and_preserves_fact_identity(tmp_path, capsys):
    store, project, request = _handoff(tmp_path)
    path = tmp_path / "transition.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    args = [
        "costs",
        "transition",
        "--project",
        str(project),
        "--request",
        str(path),
        "--json",
    ]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    before = store.capture()
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["replayed"] is True
    assert second["factId"] == first["factId"]
    assert store.capture() == before


def test_transition_mcp_uses_structured_request_and_existing_review_boundary(tmp_path):
    store, project, request = _handoff(tmp_path)
    definition = next(
        d for d in all_bridge_defs() if d.spec.name == "avo_costs_transition"
    )
    assert definition.spec.destructive is True
    assert next(p for p in definition.params if p.name == "request").required is True
    result = run_bridged(
        ("costs", "transition"),
        {"project": str(project), "request": request, "as_json": True},
    )
    assert result.ok
    assert result.parsed_json["schemaVersion"] == "2.0.0"
    assert (
        result.parsed_json["accountingVideoId"] == store.identity()["accountingVideoId"]
    )
    assert len(store.documents("participations")) == 3
