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


def test_artcraft_job_bridge_shares_structured_prepare_and_exact_head_lifecycle(
    tmp_path, monkeypatch
):
    from avo import init_project
    from avo.adapters.artcraft import SelectedArtCraftAdapter
    from avo.mcp.tools.cli_tools import all_bridge_defs
    from tests.test_artcraft_jobs import AuthoringApp, job_spec

    fake = AuthoringApp(tmp_path)
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    monkeypatch.setattr(
        SelectedArtCraftAdapter,
        "observe",
        lambda _self, **selection: fake.observe(**selection),
    )
    monkeypatch.setattr(
        SelectedArtCraftAdapter,
        "validate_run",
        lambda _self, job: fake.validate_run(job),
    )
    monkeypatch.setattr(
        SelectedArtCraftAdapter,
        "author_lower_third",
        lambda _self, job, directory: fake.author_lower_third(job, directory),
    )
    operations = {"prepare", "run", "inspect", "recover"}
    tools = {
        tool.cli_prefix[-1]: tool
        for tool in all_bridge_defs()
        if tool.cli_prefix[:1] == ("artcraft",) and tool.cli_prefix[-1] in operations
    }
    assert set(tools) == operations
    assert all(not tool.spec.destructive for tool in tools.values())
    args = {
        "request": request(purpose='Identify "Caf\u00e9" on screen'),
        "job_spec": job_spec(
            tmp_path, authoringParameters={"primaryText": "Caf\u00e9", "font": "Arial"}
        ),
        "provider": "neutral-channel",
        "workspace": str(tmp_path),
        "app": "anicraft",
        "mode": "cli",
        "operation": ["lower-third"],
        "as_json": True,
    }
    prepared = run_bridged(tools["prepare"].cli_prefix, args)
    assert prepared.ok, prepared.stderr
    direct = run_cli(
        [
            "artcraft",
            "prepare",
            "--request-json",
            json.dumps(args["request"]),
            "--job-spec-json",
            json.dumps(args["job_spec"]),
            "--provider",
            args["provider"],
            "--workspace",
            args["workspace"],
            "--app",
            args["app"],
            "--mode",
            args["mode"],
            "--operation",
            "lower-third",
            "--json",
        ]
    )
    assert direct.ok, direct.stderr
    assert direct.parsed_json == prepared.parsed_json
    selector = {
        "job": prepared.parsed_json["jobRef"],
        "expected_head": prepared.parsed_json["head"],
        "as_json": True,
    }

    def call(operation, selected):
        return run_bridged(tools[operation].cli_prefix, selected)

    recovered = call("recover", selector)
    assert recovered.ok, recovered.stderr
    assert recovered.parsed_json["recovery"]["nextAction"] == "run-prepared-job"
    rendered = call("run", selector)
    assert rendered.ok, rendered.stderr
    retried = call("recover", {**selector, "action": "retry"})
    assert retried.ok, retried.stderr
    assert retried.parsed_json == rendered.parsed_json
    stale = call("inspect", selector)
    assert not stale.ok
    selected = {**selector, "expected_head": rendered.parsed_json["head"]}
    for operation in ("run", "inspect", "recover"):
        bridged = call(operation, selected)
        direct = run_cli(
            [
                "artcraft",
                operation,
                "--job",
                selected["job"],
                "--expected-head",
                selected["expected_head"],
                "--json",
            ]
        )
        assert bridged.ok, bridged.stderr
        assert bridged.parsed_json == direct.parsed_json
    assert len(fake.executions) == 2


def test_artcraft_mcp_rejects_a_client_path_as_job_specification():
    result = run_bridged(
        ("artcraft", "prepare"), {"job_spec": "client-job.json", "as_json": True}
    )
    assert not result.ok
    assert json.loads(result.stderr)["code"] == "ARTCRAFT_INVALID_REQUEST"
