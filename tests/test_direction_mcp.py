"""MCP advertises and invokes the shared creative CLI, with exact decisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from avo.mcp import mrtr
from avo.mcp.bridge import BridgeResult, kwargs_to_argv, run_bridged, run_cli
from avo.mcp.registry import get_tool
from avo.mcp.tools import cli_tools
from tests.test_briefstart_context import project_fixture

OPERATIONS = {
    "direction": ("catalog", "prepare", "propose", "decide", "show"),
    "briefstart": ("prepare", "propose", "decide", "show"),
}


def definition(name):
    values = {item.spec.name: item for item in cli_tools.all_bridge_defs()}
    assert name in values, f"MCP is missing the native creative operation {name}"
    return values[name]


@pytest.mark.parametrize(
    "group,operation",
    [(group, op) for group, operations in OPERATIONS.items() for op in operations],
)
def test_every_creative_operation_has_one_native_bridge(group, operation):
    name = f"avo_{group}_{operation}"
    item = definition(name)
    assert item.cli_prefix == (group, operation)
    assert item.spec.cli_argv_template == (group, operation)
    assert item.spec.group == group
    assert get_tool(name) == item.spec
    params = {param.name: param for param in item.params}
    assert params["as_json"].default is True
    assert params["as_json"].annotation is bool
    assert "video_id" not in params, "Do not advertise a flag the creative CLI rejects"
    if group == "briefstart":
        assert params["project"].required is True
    else:
        assert "project" not in params
        assert params["provider"].required is False
    if operation in {"propose", "decide"}:
        assert params["request"].required is True


@pytest.mark.parametrize("group", list(OPERATIONS))
def test_creator_decisions_are_high_impact_and_reads_are_not(group):
    assert definition(f"avo_{group}_decide").spec.destructive is True
    for operation in OPERATIONS[group]:
        item = definition(f"avo_{group}_{operation}")
        if operation != "decide":
            assert item.spec.destructive is False
        if operation in {"prepare", "propose"}:
            description = item.spec.description.casefold()
            assert "writ" in description or "mutat" in description
            assert "read-only" not in description


def test_optional_repeated_inputs_match_native_parser_names():
    direction = {p.name: p for p in definition("avo_direction_prepare").params}
    assert direction["profile_id"].required is True
    assert "list[str]" in str(direction["entry"].annotation)
    assert direction["entry"].default is None
    assert direction["refresh_from"].required is False
    brief = {p.name: p for p in definition("avo_briefstart_prepare").params}
    assert brief["direction"].required is False
    assert brief["context"].required is False
    assert "list[str]" in str(brief["reference"].annotation)
    assert brief["reference"].default is None
    shown = {p.name: p for p in definition("avo_direction_show").params}
    assert shown["ref"].required is True
    assert shown["check_sources"].annotation is bool


def test_pipeline_bridge_exposes_optional_direction_without_new_requirement():
    params = {p.name: p for p in definition("avo_pipeline_run").params}
    for name in ("direction", "brief_context", "direction_reference"):
        assert name in params
        assert params[name].required is False
    assert "list[str]" in str(params["direction_reference"].annotation)


def test_repeatable_reference_flags_and_mrtr_fields_never_change_cli_semantics():
    item = definition("avo_briefstart_prepare")
    argv = kwargs_to_argv(
        item.cli_prefix,
        {
            "project": "new-video.json",
            "direction": "references",
            "context": None,
            "reference": ["one.json", "two.json"],
            "as_json": True,
        },
    )
    assert argv == [
        "briefstart",
        "prepare",
        "--project",
        "new-video.json",
        "--direction",
        "references",
        "--reference",
        "one.json",
        "--reference",
        "two.json",
        "--json",
    ]


def test_none_bridge_and_native_cli_have_same_result_without_new_artistic_files(
    tmp_path,
):
    project = project_fixture(tmp_path)
    item = definition("avo_briefstart_prepare")
    args = {"project": str(project), "direction": "none", "as_json": True}
    native = run_cli(kwargs_to_argv(item.cli_prefix, args))
    bridged = run_bridged(
        item.cli_prefix, {**args, "requestState": "ignored", "inputResponses": {}}
    )
    assert native.exit_code == bridged.exit_code == 0
    assert native.parsed_json == bridged.parsed_json
    assert bridged.parsed_json["status"] == "bypassed"
    assert not (project.parent / "edit/briefstart").exists()


def test_bridge_preserves_native_invalid_request_status_and_nonzero_exit(tmp_path):
    project = project_fixture(tmp_path)
    bad = tmp_path / "decision.json"
    bad.write_text('{"scope":"provider","action":"accept"}', encoding="utf-8")
    item = definition("avo_briefstart_decide")
    args = {"project": str(project), "request": str(bad), "as_json": True}
    direct = run_cli(kwargs_to_argv(item.cli_prefix, args))
    bridged = run_bridged(item.cli_prefix, args)
    assert direct.exit_code == bridged.exit_code == 2
    assert json.loads(direct.stderr) == json.loads(bridged.stderr)
    assert json.loads(bridged.stderr)["status"] == "invalid-request"
    assert not (project.parent / "edit/briefstart/index.json").exists()


def decision_file(tmp_path: Path, *, scope: str):
    path = tmp_path / "decision.json"
    path.write_text(
        json.dumps(
            {
                "requestId": "human-decision-001",
                "targetRef": {
                    "id": "proposal-one",
                    "documentHash": "a" * 64,
                    "path": "briefs/proposal-one.json",
                },
                "expectedIndexHash": "b" * 64,
                "action": "accept" if scope == "provider" else "select",
                "scope": scope,
                "actor": {"type": "human", "id": "creator"},
                "reason": "This exact reviewed direction is selected.",
                "humanInstruction": {
                    "source": "session:message-1",
                    "text": "Select this exact version.",
                },
                **({"optionId": "quiet"} if scope == "project" else {}),
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("group", list(OPERATIONS))
def test_decision_handler_requires_confirmation_for_the_same_exact_request(
    tmp_path, monkeypatch, group
):
    mrtr.reset_process_signing_key_for_tests()
    request = decision_file(
        tmp_path, scope="provider" if group == "direction" else "project"
    )
    item = definition(f"avo_{group}_decide")
    handler = cli_tools._make_handler(item)
    calls = []

    def fake_bridge(prefix, args):
        calls.append((prefix, args))
        return BridgeResult(True, 0, "{}", "", {"status": "selected"})

    monkeypatch.setattr(cli_tools, "run_bridged", fake_bridge)
    args = {"request": str(request), "as_json": True}
    args.update(provider="neutral") if group == "direction" else args.update(
        project="new-video.json"
    )
    wire = mrtr.input_required_to_dict(handler(**args))
    assert wire["resultType"] == "input_required"
    assert not calls
    accepted = handler(
        **args,
        requestState=wire["requestState"],
        inputResponses={
            mrtr.CONFIRM_ELICITATION_KEY: {
                "action": "accept",
                "content": {"confirm": True},
            }
        },
    )
    assert accepted["ok"] is True
    expected_digest = hashlib.sha256(request.read_bytes()).hexdigest()
    assert calls == [(item.cli_prefix, {**args, "request_sha256": expected_digest})]


def test_mutated_decision_file_during_confirmation_does_not_authorize_new_target(
    tmp_path, monkeypatch
):
    mrtr.reset_process_signing_key_for_tests()
    request = decision_file(tmp_path, scope="project")
    handler = cli_tools._make_handler(definition("avo_briefstart_decide"))
    calls = []
    monkeypatch.setattr(cli_tools, "run_bridged", lambda *args: calls.append(args))
    args = {"project": "new-video.json", "request": str(request), "as_json": True}
    wire = mrtr.input_required_to_dict(handler(**args))
    changed = json.loads(request.read_text(encoding="utf-8"))
    changed["targetRef"]["documentHash"] = "c" * 64
    request.write_text(json.dumps(changed), encoding="utf-8")
    result = handler(
        **args,
        requestState=wire["requestState"],
        inputResponses={
            mrtr.CONFIRM_ELICITATION_KEY: {
                "action": "accept",
                "content": {"confirm": True},
            }
        },
    )
    assert isinstance(result, dict) and result["ok"] is False
    assert not calls


def test_last_moment_file_change_is_rejected_by_the_native_single_read(
    tmp_path, monkeypatch
):
    mrtr.reset_process_signing_key_for_tests()
    project = project_fixture(tmp_path)
    request = decision_file(tmp_path, scope="project")
    handler = cli_tools._make_handler(definition("avo_briefstart_decide"))
    args = {"project": str(project), "request": str(request), "as_json": True}
    wire = mrtr.input_required_to_dict(handler(**args))
    original_bridge = cli_tools.run_bridged

    def mutate_before_native_read(prefix, arguments):
        changed = json.loads(request.read_text(encoding="utf8"))
        changed["targetRef"]["documentHash"] = "c" * 64
        request.write_text(json.dumps(changed), encoding="utf8")
        return original_bridge(prefix, arguments)

    monkeypatch.setattr(cli_tools, "run_bridged", mutate_before_native_read)
    result = handler(
        **args,
        requestState=wire["requestState"],
        inputResponses={
            mrtr.CONFIRM_ELICITATION_KEY: {
                "action": "accept",
                "content": {"confirm": True},
            }
        },
    )
    assert result["ok"] is False
    assert json.loads(result["stderr"])["status"] == "stale"
    assert not (project.parent / "edit/briefstart/index.json").exists()
