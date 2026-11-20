"""Editing craft discovery stays separate from execution and canonical ownership."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from avo.mcp.bridge import kwargs_to_argv, run_cli
from avo.mcp.tools.cli_tools import _make_handler, all_bridge_defs
from avo.timeline.command_registry import CommandPermissionError, authorize
from tests.test_motion_review_default_flow import _tree


def _tool(group, operation):
    definitions = [
        item for item in all_bridge_defs() if item.cli_prefix == (group, operation)
    ]
    assert len(definitions) == 1
    return definitions[0]


@pytest.mark.parametrize(
    ("group", "operation"),
    [
        ("animation", "plan-show"),
        ("sfx", "show"),
        ("timeline-export", "status"),
    ],
)
def test_read_only_native_and_mcp_defaults_never_start_jobs(
    group, operation, footage_project_factory, monkeypatch
):
    workspace = footage_project_factory()
    before = _tree(workspace.raw_dir)
    definition = _tool(group, operation)
    args = {"project": str(workspace.project_path), "as_json": True}

    def forbidden(*args, **kwargs):
        pytest.fail("A default metadata view attempted process execution")

    monkeypatch.setattr(subprocess, "run", forbidden)
    native = run_cli(kwargs_to_argv(definition.cli_prefix, args))
    bridged = _make_handler(definition)(**args)

    assert not definition.spec.destructive
    assert native.exit_code == 0, native.stderr
    assert bridged == native.to_dict()
    assert _tree(workspace.raw_dir) == before
    if group == "animation":
        snapshot = native.parsed_json["snapshot"]
        assert "items" in snapshot and "storyboardCards" in snapshot


@pytest.mark.parametrize(
    ("group", "operation"),
    [
        ("animation", "camera-apply"),
        ("sfx", "apply"),
        ("preparation", "recover"),
        ("timeline-export", "apply-feedback"),
    ],
)
def test_mcp_application_requires_confirmation_before_invoking_normal_owner(
    tmp_path, monkeypatch, group, operation
):
    from avo.mcp import mrtr
    from avo.mcp.tools import cli_tools

    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    definition = _tool(group, operation)
    assert definition.spec.destructive

    def forbidden(*args, **kwargs):
        pytest.fail("A pending request reached the canonical owner")

    monkeypatch.setattr(cli_tools, "run_bridged", forbidden)
    result = _make_handler(definition)(
        project=str(tmp_path / "project.json"),
        request=str(request),
        ctx=SimpleNamespace(client_capabilities={"elicitation": {}}),
        as_json=True,
    )
    assert mrtr.input_required_to_dict(result)["resultType"] == "input_required"


def test_descriptor_search_cannot_select_model_execution(
    footage_project_factory, tmp_path, monkeypatch
):
    from avo import sfx_cli

    workspace = footage_project_factory()
    request = tmp_path / "search.json"
    request.write_text(
        json.dumps(
            {
                "contractVersion": "1.0.0",
                "operation": "search",
                "operationId": "try-semantic",
                "query": "Soft click",
                "mode": "semantic",
            }
        ),
        encoding="utf-8",
    )
    args = {
        "project": str(workspace.project_path),
        "request": str(request),
        "as_json": True,
    }

    def forbidden(*args, **kwargs):
        pytest.fail("An invalid search request reached sound discovery")

    monkeypatch.setattr(sfx_cli, "_catalogue", forbidden)
    definition = _tool("sfx", "search")
    semantic = _tool("sfx", "search-semantic")
    native = run_cli(kwargs_to_argv(definition.cli_prefix, args))

    assert native.exit_code == 2
    assert _make_handler(definition)(**args) == native.to_dict()
    assert semantic.cli_prefix != definition.cli_prefix
    assert "model execution" in semantic.spec.description


@pytest.mark.parametrize("command", ["talking-head", "direction", "exports"])
@pytest.mark.parametrize("artifact", ["cmap", "bmap", "tracks", "animation"])
def test_profile_and_admin_surfaces_cannot_claim_canonical_writes(command, artifact):
    with pytest.raises(
        CommandPermissionError, match="cannot mutate canonical artifact"
    ):
        authorize(command, mutation=artifact)
