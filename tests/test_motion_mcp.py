"""Motion preference MCP discovery and transport match the native commands."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import get_args

import pytest

from avo.mcp.bridge import kwargs_to_argv, run_bridged, run_cli
from avo.mcp.tools import cli_tools

PREFERENCE_TOOLS = {
    "avo_animation_engine_show": "engine-show",
    "avo_animation_engine_set": "engine-set",
    "avo_animation_engine_reset": "engine-reset",
}


def definition(name):
    # Package import-hygiene tests intentionally replace the MCP module graph.
    from avo.mcp.tools import cli_tools

    matches = [item for item in cli_tools.all_bridge_defs() if item.spec.name == name]
    assert len(matches) == 1, f"Expected exactly one registered motion tool: {name}"
    return matches[0]


@pytest.fixture
def isolated_motion_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("AVO_ROOT", raising=False)
    return home


@pytest.mark.parametrize("name,operation", PREFERENCE_TOOLS.items())
def test_preference_tools_are_discoverable_with_optional_context(name, operation):
    from avo.mcp.registry import get_tool

    item = definition(name)
    assert item.cli_prefix == ("animation", operation)
    assert item.spec.cli_argv_template == ("animation", operation)
    assert item.spec.group == "animation"
    assert get_tool(name) == item.spec
    params = {param.name: param for param in item.params}
    assert params["as_json"].default is True
    assert params["as_json"].annotation is bool
    assert params["project"].required is False
    assert params["provider"].required is False
    assert "video_id" not in params
    expected = {"project", "provider", "as_json"}
    if operation == "engine-show":
        expected.add("motion_engine")
        assert params["motion_engine"].required is False
    else:
        expected.add("scope")
        assert params["scope"].required is True
        if operation == "engine-set":
            expected.add("engine")
            assert params["engine"].required is True
    assert set(params) == expected


def test_read_and_reversible_preference_tools_do_not_add_confirmation_ritual():
    assert definition("avo_animation_engine_show").spec.destructive is False
    for name in ("avo_animation_engine_set", "avo_animation_engine_reset"):
        item = definition(name)
        assert item.spec.destructive is False
        description = item.spec.description.casefold()
        assert any(word in description for word in ("writ", "mutat", "save", "reset"))
        assert "read-only" not in description


@pytest.mark.parametrize(
    "name,kwargs,expected",
    [
        (
            "avo_animation_engine_show",
            {
                "project": None,
                "provider": None,
                "motion_engine": "code-drawn",
                "as_json": True,
            },
            ["animation", "engine-show", "--motion-engine", "code-drawn", "--json"],
        ),
        (
            "avo_animation_engine_set",
            {
                "scope": "global",
                "project": None,
                "provider": None,
                "engine": "remotion",
                "as_json": True,
            },
            [
                "animation",
                "engine-set",
                "--scope",
                "global",
                "--engine",
                "remotion",
                "--json",
            ],
        ),
        (
            "avo_animation_engine_reset",
            {
                "scope": "provider",
                "provider": "channel-a",
                "project": None,
                "as_json": True,
            },
            [
                "animation",
                "engine-reset",
                "--scope",
                "provider",
                "--provider",
                "channel-a",
                "--json",
            ],
        ),
    ],
)
def test_motion_parameter_flags_are_exact(name, kwargs, expected):
    item = definition(name)
    assert kwargs_to_argv(item.cli_prefix, kwargs) == expected
    signature = inspect.signature(cli_tools._make_handler(item))
    for key in ("project", "provider"):
        assert signature.parameters[key].default is None


def test_registered_handlers_advertise_the_same_new_preference_tools():
    handlers = {}

    class Server:
        def tool(self, *, name, description):
            def register(handler):
                handlers[name] = handler
                return handler

            return register

    specs = cli_tools.register_cli_tools(Server())
    names = [item.name for item in specs]
    for name in PREFERENCE_TOOLS:
        assert names.count(name) == 1
        assert name in handlers
        assert inspect.signature(handlers[name]).parameters["project"].default is None


def test_show_mcp_and_native_results_match_without_any_project(isolated_motion_home):
    item = definition("avo_animation_engine_show")
    kwargs = {"motion_engine": "remotion", "as_json": True}
    native = run_cli(kwargs_to_argv(item.cli_prefix, kwargs))
    bridged = run_bridged(
        item.cli_prefix, {**kwargs, "requestState": "ignored", "inputResponses": {}}
    )
    assert native.exit_code == bridged.exit_code == 0
    assert native.parsed_json == bridged.parsed_json
    assert bridged.parsed_json["selection"]["engine"] == "remotion"
    assert bridged.parsed_json["selection"]["source"] == "invocation"
    assert bridged.parsed_json["readiness"]["ready"] is False
    assert not (isolated_motion_home / ".avo/preferences.json").exists()


def test_mcp_handler_saves_and_resets_global_without_project(isolated_motion_home):
    setter = cli_tools._make_handler(definition("avo_animation_engine_set"))
    result = setter(scope="global", engine="remotion", as_json=True)
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["parsed_json"]["selection"]["engine"] == "remotion"
    assert result["parsed_json"]["readiness"]["ready"] is False
    preference = isolated_motion_home / ".avo/preferences.json"
    assert json.loads(preference.read_text(encoding="utf-8"))["motion"]["engine"] == (
        "remotion"
    )
    resetter = cli_tools._make_handler(definition("avo_animation_engine_reset"))
    reset = resetter(scope="global", as_json=True)
    assert reset["ok"] is True
    assert reset["parsed_json"]["selection"]["source"] == "default"


@pytest.mark.parametrize(
    "name,kwargs",
    [
        (
            "avo_animation_engine_set",
            {"scope": "global", "engine": "canvas", "as_json": True},
        ),
        (
            "avo_animation_engine_set",
            {"scope": "provider", "engine": "code-drawn", "as_json": True},
        ),
        ("avo_animation_engine_reset", {"scope": "project", "as_json": True}),
    ],
)
def test_invalid_mcp_requests_preserve_native_nonzero_errors(
    isolated_motion_home, name, kwargs
):
    item = definition(name)
    native = run_cli(kwargs_to_argv(item.cli_prefix, kwargs))
    bridged = run_bridged(item.cli_prefix, kwargs)
    assert native.exit_code == bridged.exit_code == 2
    assert native.stderr == bridged.stderr
    assert native.stdout == bridged.stdout == ""
    assert not (isolated_motion_home / ".avo/preferences.json").exists()


AUTHORING_TOOLS = {
    "avo_animation_runtime_install": "runtime-install",
    "avo_animation_code_drawn_scaffold": "code-drawn-scaffold",
    "avo_animation_code_drawn_check": "code-drawn-check",
    "avo_animation_code_drawn_snapshot": "code-drawn-snapshot",
    "avo_animation_code_drawn_render": "code-drawn-render",
}


@pytest.mark.parametrize("name,operation", AUTHORING_TOOLS.items())
def test_code_drawn_tools_are_discoverable_without_footage_context(name, operation):
    from avo.mcp.registry import get_tool

    item = definition(name)
    assert item.cli_prefix == ("animation", operation)
    assert item.spec.cli_argv_template == ("animation", operation)
    assert get_tool(name) == item.spec
    assert item.spec.destructive is False
    params = {parameter.name: parameter for parameter in item.params}
    assert params["as_json"].default is True
    assert params["as_json"].annotation is bool
    assert "project" not in params
    assert "provider" not in params
    assert "video_id" not in params
    if operation == "runtime-install":
        assert params["engine"].required is True
        assert get_args(params["engine"].annotation) == ("code-drawn",)
        assert params["brush"].annotation is bool
        assert params["brush"].default is False
    elif operation == "code-drawn-scaffold":
        for field in ("destination", "route", "width", "height", "fps", "frames"):
            assert params[field].required is True
        for field in ("width", "height", "frames"):
            assert params[field].annotation is int
        assert params["background"].default == "opaque"
        assert params["background_color"].default is None
    else:
        assert params["composition"].required is True
        if operation == "code-drawn-check":
            assert params["input_lock"].required is False
            assert params["output_lock"].required is False
        elif operation == "code-drawn-snapshot":
            assert params["frame"].required is True
            assert params["frame"].annotation is int
            assert params["output"].required is True
            assert params["input_lock"].required is False
        else:
            assert params["input_lock"].required is True
            assert params["output"].required is True


def test_code_drawn_tool_disclosures_distinguish_network_and_conditional_writes():
    install = definition("avo_animation_runtime_install").spec.description.casefold()
    assert "network" in install
    assert "download" in install or "provision" in install
    check = definition("avo_animation_code_drawn_check").spec.description.casefold()
    assert "lock" in check
    assert "writ" in check
    for name in AUTHORING_TOOLS:
        if name == "avo_animation_runtime_install":
            continue
        description = definition(name).spec.description.casefold()
        assert "no download" in description or "does not download" in description


def authoring_arguments(operation, tmp_path):
    composition = str(tmp_path / "composition.json")
    lock = str(tmp_path / "input-lock.json")
    common = {"as_json": True}
    if operation == "runtime-install":
        return (
            {"engine": "code-drawn", "brush": True, **common},
            ["--engine", "code-drawn", "--brush", "--json"],
        )
    if operation == "code-drawn-scaffold":
        destination = str(tmp_path / "new-scene")
        return (
            {
                "destination": destination,
                "route": "svg",
                "width": 1280,
                "height": 720,
                "fps": "30000/1001",
                "frames": 90,
                "background": "transparent",
                "background_color": None,
                **common,
            },
            [
                "--destination",
                destination,
                "--route",
                "svg",
                "--width",
                "1280",
                "--height",
                "720",
                "--fps",
                "30000/1001",
                "--frames",
                "90",
                "--background",
                "transparent",
                "--json",
            ],
        )
    if operation == "code-drawn-check":
        return (
            {
                "composition": composition,
                "input_lock": None,
                "output_lock": lock,
                **common,
            },
            ["--composition", composition, "--output-lock", lock, "--json"],
        )
    output = str(
        tmp_path / ("frame.png" if operation.endswith("snapshot") else "asset.mkv")
    )
    if operation == "code-drawn-snapshot":
        return (
            {
                "composition": composition,
                "frame": 17,
                "output": output,
                "input_lock": lock,
                **common,
            },
            [
                "--composition",
                composition,
                "--frame",
                "17",
                "--output",
                output,
                "--input-lock",
                lock,
                "--json",
            ],
        )
    return (
        {"composition": composition, "input_lock": lock, "output": output, **common},
        [
            "--composition",
            composition,
            "--input-lock",
            lock,
            "--output",
            output,
            "--json",
        ],
    )


@pytest.mark.parametrize("name,operation", AUTHORING_TOOLS.items())
def test_code_drawn_tool_flags_are_exact_and_do_not_leak_context(
    tmp_path, name, operation
):
    item = definition(name)
    kwargs, suffix = authoring_arguments(operation, tmp_path)
    assert kwargs_to_argv(item.cli_prefix, kwargs) == ["animation", operation, *suffix]
    signature = inspect.signature(cli_tools._make_handler(item))
    assert signature.parameters["as_json"].default is True


@pytest.mark.parametrize("name,operation", AUTHORING_TOOLS.items())
def test_code_drawn_flags_match_the_native_parser(tmp_path, name, operation):
    from avo.cli import build_parser

    item = definition(name)
    kwargs, _ = authoring_arguments(operation, tmp_path)
    parsed = build_parser().parse_args(kwargs_to_argv(item.cli_prefix, kwargs))
    assert parsed.command == "animation"
    assert parsed.animation_command == operation
    assert parsed.as_json is True
    for field in ("width", "height", "frames", "frame"):
        if field in kwargs:
            assert getattr(parsed, field) == kwargs[field]


def test_canonical_materialize_and_review_are_native_one_to_one_tools():
    definitions = {item.spec.name: item for item in cli_tools._core_bridge_defs()}
    materialize = definitions["avo_animation_materialize"]
    assert materialize.cli_prefix == ("animation", "materialize")
    assert {item.name for item in materialize.params} >= {
        "project",
        "instance_id",
        "output",
    }
    review = definitions["avo_animation_code_drawn_review"]
    assert review.cli_prefix == ("animation", "code-drawn-review")
    names = [item.name for item in review.params]
    assert len(names) == len(set(names))
    assert {
        "candidate",
        "source_receipt",
        "output",
        "sample_frame",
        "transition",
        "loop",
    } <= set(names)
    assert not review.spec.destructive


def test_new_motion_help_uses_the_public_engine_cli_prefix():
    from avo.mcp.tools.cli_tools import all_bridge_defs

    operations = {
        "engine-show",
        "engine-set",
        "engine-reset",
        "runtime-install",
        "code-drawn-scaffold",
        "code-drawn-check",
        "code-drawn-snapshot",
        "code-drawn-render",
        "code-drawn-review",
        "materialize",
    }
    observed = set()
    for item in all_bridge_defs():
        argv = item.spec.cli_argv_template
        if len(argv) == 2 and argv[0] == "animation" and argv[1] in operations:
            assert "CLI: avo cli animation " + argv[1] + ")" in item.spec.description
            observed.add(argv[1])
    assert observed == operations
