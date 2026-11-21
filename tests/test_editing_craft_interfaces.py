"""Craft preference requests stay typed and share native/MCP handlers."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.mcp.bridge import kwargs_to_argv, run_bridged, run_cli


def request(operation="options-set"):
    value = {
        "contractVersion": "1.0.0",
        "operation": operation,
        "operationId": "craft-preferences-1",
        "actor": "creator",
        "reason": "Choose the next authoring treatment",
        "expectedBasis": {},
        "selection": {"scope": "global"},
        "expectedDocument": "absent",
    }
    if operation == "options-set":
        value["patch"] = {"camera": {"enabled": True}}
    return value


def definition(operation):
    from avo.mcp.tools.cli_tools import all_bridge_defs

    matches = [
        item
        for item in all_bridge_defs()
        if item.spec.name == "avo_animation_" + operation.replace("-", "_")
    ]
    assert len(matches) == 1
    return matches[0]


@pytest.fixture
def craft_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("AVO_ROOT", raising=False)
    return home


@pytest.mark.parametrize("operation", ["options-set", "options-reset"])
def test_valid_preference_request_is_copied_and_scope_explicit(operation):
    from avo.editing_craft_requests import validate_craft_request

    value = request(operation)
    result = validate_craft_request(value, operation=operation)
    assert result == value
    assert result is not value
    assert result["selection"] is not value["selection"]


@pytest.mark.parametrize(
    "change",
    [
        {"contractVersion": "2.0.0"},
        {"operation": "camera-apply"},
        {"operationId": ""},
        {"actor": ""},
        {"reason": ""},
        {"expectedDocument": "latest"},
        {"expectedBasis": {"cmap": "pretend-head"}},
        {"selection": {"scope": "invocation"}},
        {"selection": {"scope": "global", "owner": "avo.motion"}},
        {"patch": {"enableMotionMap": False}},
        {"patch": {"camera": {"enabled": "yes"}}},
        {"code": "arbitrary expression"},
    ],
)
def test_invalid_requests_fail_before_any_preference_change(change):
    from avo.editing_craft_requests import CraftRequestError, validate_craft_request

    value = {**request(), **change}
    original = deepcopy(value)
    with pytest.raises(CraftRequestError):
        validate_craft_request(value, operation="options-set")
    assert value == original


def test_reset_request_cannot_smuggle_set_patch():
    from avo.editing_craft_requests import CraftRequestError, validate_craft_request

    value = request("options-reset")
    value["patch"] = {"camera": {"enabled": False}}
    with pytest.raises(CraftRequestError):
        validate_craft_request(value, operation="options-reset")


def test_request_loader_requires_absolute_path_and_bounded_json(tmp_path):
    from avo.editing_craft_requests import CraftRequestError, load_craft_request

    with pytest.raises(CraftRequestError):
        load_craft_request(Path("relative.json"), operation="options-set")
    path = tmp_path / "request.json"
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(CraftRequestError):
        load_craft_request(path, operation="options-set")
    path.write_text('{"operation":', encoding="utf-8")
    with pytest.raises(CraftRequestError):
        load_craft_request(path, operation="options-set")


@pytest.mark.parametrize(
    "raw",
    [
        '{"operation":"options-set","operation":"options-reset"}',
        '{"patch":{"camera":{"enabled":NaN}}}',
    ],
)
def test_request_json_rejects_duplicate_fields_and_nonfinite_values(tmp_path, raw):
    from avo.editing_craft_requests import CraftRequestError, load_craft_request

    path = tmp_path / "invalid.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(CraftRequestError):
        load_craft_request(path, operation="options-set")


@pytest.mark.parametrize("operation", ["options-show", "options-set", "options-reset"])
def test_mcp_options_are_explicit_and_share_native_arguments(operation, tmp_path):
    item = definition(operation)
    assert item.cli_prefix == ("animation", operation)
    assert item.spec.destructive is False
    parameters = {param.name: param for param in item.params}
    assert parameters["project"].required is False
    assert parameters["provider"].required is False
    args = {"as_json": True}
    expected = ["animation", operation, "--json"]
    if operation == "options-show":
        assert "request" not in parameters
        assert "read-only" in item.spec.description.casefold()
    else:
        assert parameters["request"].required is True
        args["request"] = str(tmp_path / "request.json")
        expected += ["--request", args["request"]]
        description = item.spec.description.casefold()
        assert "preference" in description and "read-only" not in description
    assert kwargs_to_argv(item.cli_prefix, args) == expected


def test_show_is_native_mcp_equivalent_without_writes_or_jobs(craft_home, monkeypatch):
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail("Preference inspection must not execute a process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    native = run_cli(["animation", "options-show", "--json"])
    assert native.exit_code == 0, native.stderr
    bridged = run_bridged(definition("options-show").cli_prefix, {"as_json": True})
    assert bridged == native
    value = native.parsed_json
    assert value["operation"] == "options-show"
    assert value["effect"] == "metadata-read"
    assert value["builtIn"] == {"motionMap": True, "storyboard": True}
    assert value["selection"]["effective"]["camera"]["enabled"] is False
    assert list(craft_home.iterdir()) == []


def test_set_and_reset_need_exact_document_identity(craft_home, tmp_path, monkeypatch):
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail("Preference mutation must not execute a process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    path = tmp_path / "request.json"
    value = request()
    path.write_text(json.dumps(value), encoding="utf-8")
    result = run_cli(["animation", "options-set", "--request", str(path), "--json"])
    assert result.exit_code == 0, result.stderr
    saved = json.loads((craft_home / ".avo/preferences.json").read_text())
    assert saved["editingCraft"]["camera"]["enabled"] is True
    assert result.parsed_json["effect"] == "preference-write"
    assert result.parsed_json["operationId"] == value["operationId"]
    before = (craft_home / ".avo/preferences.json").read_bytes()
    stale = run_cli(["animation", "options-set", "--request", str(path), "--json"])
    assert stale.exit_code != 0
    assert (craft_home / ".avo/preferences.json").read_bytes() == before
    reset = request("options-reset")
    reset["expectedDocument"] = result.parsed_json["after"]
    path.write_text(json.dumps(reset), encoding="utf-8")
    response = run_bridged(
        definition("options-reset").cli_prefix,
        {
            "request": str(path),
            "as_json": True,
        },
    )
    assert response.exit_code == 0, response
    assert "editingCraft" not in json.loads(
        (craft_home / ".avo/preferences.json").read_text()
    )


def test_invalid_or_wrong_operation_request_preserves_preferences(craft_home, tmp_path):
    path = tmp_path / "request.json"
    value = request("options-reset")
    path.write_text(json.dumps(value), encoding="utf-8")
    response = run_cli(["animation", "options-set", "--request", str(path), "--json"])
    assert response.exit_code != 0
    assert list(craft_home.iterdir()) == []


@pytest.mark.parametrize("operation", ["options-show", "options-set", "options-reset"])
def test_relative_project_context_is_rejected_before_read_or_write(
    craft_home, operation
):
    args = ["animation", operation, "--project", "relative/avo.project.json", "--json"]
    if operation != "options-show":
        args += ["--request", "also-relative.json"]
    response = run_cli(args)
    assert response.exit_code == 2
    assert json.loads(response.stderr)["code"] == "CRAFT_PATH_INVALID"
    assert list(craft_home.iterdir()) == []


def test_engine_cli_prefix_reuses_the_native_options_handler(craft_home, capsys):
    from avo.engine_cli import main

    assert main(["cli", "animation", "options-show", "--json"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["operation"] == "options-show"
    assert value["effect"] == "metadata-read"
