"""Structured cost metadata crosses MCP only through reviewed, scoped operations."""

import inspect
import json
from pathlib import Path
from typing import get_origin

import pytest

from avo.cost_store import CostError
from avo.mcp import bridge, mrtr
from avo.mcp.tools import cli_tools


def _definition(name):
    definitions = {item.spec.name: item for item in cli_tools.all_bridge_defs()}
    assert name in definitions, f"missing structured cost tool: {name}"
    return definitions[name]


@pytest.fixture(autouse=True)
def isolated_mcp_cost_locations(monkeypatch, tmp_path):
    from avo import avo_state, cost_history

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cost_history, "providers_dir", lambda: tmp_path / "providers")


@pytest.fixture
def cost_mcp_input(tmp_path, monkeypatch):
    from avo import avo_state
    from test_cost_continuity import (
        context_descriptor,
        evidence,
        packet,
        registered_ledger,
    )
    from test_costs import fact

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    mrtr.reset_process_signing_key_for_tests()
    store = registered_ledger(tmp_path)
    row = fact()
    usage = packet(store, [row], evidence_rows=[evidence(row, nature="manual")])
    return {
        "store": store,
        "project": str(store.raw_dir / "avo.project.json"),
        "descriptor": context_descriptor(),
        "packet": usage,
    }


@pytest.mark.parametrize(
    ("name", "field"),
    [("avo_costs_context", "descriptor"), ("avo_costs_observe", "packet")],
)
def test_cost_mcp_tools_require_structured_metadata_and_mutation_review(name, field):
    definition = _definition(name)
    assert definition.spec.destructive is True
    parameter = next(item for item in definition.params if item.name == field)
    assert parameter.required is True
    assert parameter.annotation is dict or get_origin(parameter.annotation) is dict
    names = {item.name for item in definition.params}
    assert not names.intersection({"file", "allow_synthetic", "payload_json"})
    signature = inspect.signature(cli_tools._make_handler(definition))
    assert field in signature.parameters
    assert "ctx" in signature.parameters


@pytest.mark.parametrize(
    "operation,field",
    [
        ("context", "descriptor"),
        ("observe", "packet"),
        ("transition", "request"),
        ("estimate", "request"),
        ("reconcile", "reconciliation"),
    ],
)
def test_sdk_cost_arguments_require_structured_payload_and_drop_cli_overrides(
    operation, field
):
    tool_type = pytest.importorskip("mcp.server.mcpserver.tools.base").Tool
    validation_error = pytest.importorskip("pydantic").ValidationError
    handler = cli_tools._make_handler(_definition(f"avo_costs_{operation}"))
    tool = tool_type.from_function(handler)
    assert field in tool.parameters["required"]
    overrides = {
        "file": "/server/PRIVATE-SDK-SENTINEL.json",
        "payload_json": "{}",
    }
    for name, value in overrides.items():
        with pytest.raises(validation_error):
            tool.fn_metadata.validate_arguments({"project": "synthetic", name: value})
    parsed = tool.fn_metadata.validate_arguments(
        {"project": "synthetic", field: {}, **overrides}
    )
    assert parsed[field] == {}
    assert not overrides.keys() & parsed.keys()


@pytest.mark.parametrize(
    "operation,field", [("context", "descriptor"), ("observe", "packet")]
)
def test_cost_mcp_metadata_uses_json_transport_without_client_files(
    cost_mcp_input, operation, field
):
    payload = cost_mcp_input[field]
    argv = bridge.kwargs_to_argv(
        ("costs", operation),
        {"project": cost_mcp_input["project"], field: payload, "as_json": True},
    )
    assert "--payload-json" in argv
    assert json.loads(argv[argv.index("--payload-json") + 1]) == payload
    assert f"--{field}" not in argv
    assert "--file" not in argv


@pytest.mark.parametrize("operation", ["run", "resume"])
def test_inline_pipeline_cost_context_is_json_not_python_mapping_repr(
    cost_mcp_input, operation
):
    argv = bridge.kwargs_to_argv(
        ("pipeline", operation),
        {
            "project": cost_mcp_input["project"],
            "cost_context": cost_mcp_input["descriptor"],
        },
    )
    assert (
        json.loads(argv[argv.index("--cost-context") + 1])
        == cost_mcp_input["descriptor"]
    )


def _assert_invalid_metadata(result):
    assert result["ok"] is False
    assert result["exit_code"] == 2
    payload = result.get("parsed_json") or json.loads(result["stderr"])
    assert payload["status"] == "invalid-input"


@pytest.mark.parametrize(
    "operation,field", [("context", "descriptor"), ("observe", "packet")]
)
def test_private_metadata_is_rejected_before_mrtr_or_cli(
    cost_mcp_input, monkeypatch, operation, field
):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("called")
        raise AssertionError(
            "invalid cost metadata must not reach mutation review or CLI"
        )

    monkeypatch.setattr(mrtr, "evaluate_destructive_gate", forbidden)
    monkeypatch.setattr(cli_tools, "run_bridged", forbidden)
    payload = {**cost_mcp_input[field], "prompt": "PRIVATE-MCP-SENTINEL"}
    handler = cli_tools._make_handler(_definition(f"avo_costs_{operation}"))
    result = handler(project=cost_mcp_input["project"], **{field: payload})
    _assert_invalid_metadata(result)
    assert calls == []
    assert "PRIVATE-MCP-SENTINEL" not in json.dumps(result)


def test_client_descriptor_path_is_rejected_without_reading_it_or_requesting_review(
    cost_mcp_input, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("a client path is not a server metadata attachment")

    monkeypatch.setattr(mrtr, "evaluate_destructive_gate", forbidden)
    monkeypatch.setattr(cli_tools, "run_bridged", forbidden)
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if "client-device" in path.parts:
            forbidden()
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    handler = cli_tools._make_handler(_definition("avo_costs_context"))
    result = handler(
        project=cost_mcp_input["project"],
        descriptor="/client-device/private/conversation.json",
    )
    _assert_invalid_metadata(result)
    assert "/client-device/private" not in json.dumps(result)


def test_invalid_structured_metadata_has_a_safe_argv_error(cost_mcp_input):
    payload = {**cost_mcp_input["descriptor"], "secret": "PRIVATE-ARGV-SENTINEL"}
    with pytest.raises(CostError) as error:
        bridge.kwargs_to_argv(("costs", "context"), {"descriptor": payload})
    assert "PRIVATE-ARGV-SENTINEL" not in str(error.value)


def test_context_mcp_preserves_review_before_mutating(cost_mcp_input):
    handler = cli_tools._make_handler(_definition("avo_costs_context"))
    store = cost_mcp_input["store"]
    before = {str(path): path.read_bytes() for path in store.root.rglob("*.json")}
    kwargs = {
        "project": cost_mcp_input["project"],
        "descriptor": cost_mcp_input["descriptor"],
        "as_json": True,
    }
    required = mrtr.input_required_to_dict(handler(**kwargs))
    assert required["resultType"] == "input_required"
    assert {
        str(path): path.read_bytes() for path in store.root.rglob("*.json")
    } == before
    approved = handler(
        **kwargs,
        requestState=required["requestState"],
        inputResponses={
            "confirm_destructive": {"action": "accept", "content": {"confirm": True}}
        },
    )
    assert approved["ok"] is True
    assert approved["parsed_json"]["schemaVersion"] == "2.0.0"
    assert (
        approved["parsed_json"]["accountingVideoId"]
        == store.identity()["accountingVideoId"]
    )


def test_structured_run_bridged_strips_transport_ids_and_retains_descriptor(
    cost_mcp_input, monkeypatch
):
    captured = []

    def fake_cli(argv):
        captured.append(argv)
        return bridge.BridgeResult(True, 0, "{}", "", {})

    monkeypatch.setattr(bridge, "run_cli", fake_cli)
    result = bridge.run_bridged(
        ("costs", "context"),
        {
            "project": cost_mcp_input["project"],
            "descriptor": cost_mcp_input["descriptor"],
            "requestState": "TRANSPORT-REQUEST-SENTINEL",
            "input_responses": {"transport-id": "TRANSPORT-RESPONSE-SENTINEL"},
            "ctx": object(),
            "as_json": True,
        },
    )
    assert result.ok is True
    argv = captured[0]
    assert (
        json.loads(argv[argv.index("--payload-json") + 1])
        == cost_mcp_input["descriptor"]
    )
    assert "TRANSPORT-" not in " ".join(argv)
    assert "--ctx" not in argv


def _approved_metadata_tool(name, **kwargs):
    handler = cli_tools._make_handler(_definition(name))
    required = mrtr.input_required_to_dict(handler(**kwargs))
    assert required["resultType"] == "input_required"
    return handler(
        **kwargs,
        requestState=required["requestState"],
        inputResponses={
            "confirm_destructive": {"action": "accept", "content": {"confirm": True}}
        },
    )


def test_mcp_manual_bootstraps_profile_from_blank_runtime_without_client_files(
    tmp_path, monkeypatch
):
    from avo import avo_state
    from test_cost_continuity import context_descriptor, production
    from test_costs import fact

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    mrtr.reset_process_signing_key_for_tests()
    store, project = production(tmp_path)
    descriptor = context_descriptor()
    descriptor["agent"]["family"] = "my-custom-executor"
    context = _approved_metadata_tool(
        "avo_costs_context", project=str(project), descriptor=descriptor, as_json=True
    )
    assert context["ok"] is True and not store.capture()["profiles"]
    request = {
        "schemaVersion": "2.0.0",
        "operationId": "structured-manual-bootstrap",
        "participationFactId": context["parsed_json"]["factId"],
        "observations": [fact(agent="my-custom-executor", model=None)],
    }
    result = _approved_metadata_tool(
        "avo_costs_report_manual", project=str(project), request=request, as_json=True
    )
    assert result["ok"] is True and result["parsed_json"]["profileId"]
    view = store.capture()
    assert (
        len(view["profiles"]) == 1
        and view["profiles"][0]["capability"] == "manual-only"
    )
    assert view["batches"][0]["evidence"][0]["nature"] == "manual"


def test_mcp_manual_client_path_is_rejected_before_read_or_review(
    cost_mcp_input, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("client path is not an observation packet")

    monkeypatch.setattr(mrtr, "evaluate_destructive_gate", forbidden)
    monkeypatch.setattr(cli_tools, "run_bridged", forbidden)
    handler = cli_tools._make_handler(_definition("avo_costs_report_manual"))
    result = handler(
        project=cost_mcp_input["project"], request="/client-device/PRIVATE-MANUAL.json"
    )
    _assert_invalid_metadata(result)
    assert "PRIVATE-MANUAL" not in json.dumps(result)


@pytest.mark.parametrize(
    "inputs", [None, [["PRIVATE-ESTIMATE-SENTINEL"]], 42, "PRIVATE-ESTIMATE-SENTINEL"]
)
def test_malformed_estimate_inputs_are_rejected_before_review_or_cli(
    cost_mcp_input, monkeypatch, inputs
):
    from test_cost_estimates import estimate_request

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid estimate must not reach review or CLI")

    monkeypatch.setattr(mrtr, "evaluate_destructive_gate", forbidden)
    monkeypatch.setattr(bridge, "run_cli", forbidden)
    monkeypatch.setattr(cli_tools, "run_bridged", forbidden)
    store = cost_mcp_input["store"]
    before = store.capture()
    kwargs = {
        "project": cost_mcp_input["project"],
        "request": estimate_request(store, inputs=inputs),
    }
    result = bridge.run_bridged(("costs", "estimate"), kwargs).to_dict()
    _assert_invalid_metadata(result)
    handler = cli_tools._make_handler(_definition("avo_costs_estimate"))
    reviewed = handler(**kwargs)
    _assert_invalid_metadata(reviewed)
    assert "PRIVATE-ESTIMATE-SENTINEL" not in json.dumps([result, reviewed])
    assert store.capture() == before
