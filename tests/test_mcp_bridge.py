"""Unit tests for avo.mcp CLI bridge (argv mapping + envelope; tmp_path only)."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from avo.mcp.bridge import kwargs_to_argv, run_bridged, run_cli, strip_mrtr_kwargs
from avo.mcp.registry import build_registry, cli_tool_specs, get_tool, tool_names
from avo.mcp.tools.cli_tools import (
    ALL_CLI_GROUPS,
    CORE_CLI_GROUPS,
    REMAINING_CLI_GROUPS,
    all_bridge_defs,
    core_bridge_defs,
    register_cli_tools,
    remaining_bridge_defs,
)


def _project(tmp_path: Path, video_id: str = "mcp-bridge") -> Path:
    path = tmp_path / "avo.project.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "bishop",
                "videoId": video_id,
                "rawDir": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_kwargs_to_argv_maps_flags_and_omits_empty() -> None:
    argv = kwargs_to_argv(
        ("pipeline", "stage"),
        {
            "project": "/tmp/p.json",
            "stage": "sources-ready",
            "payload": None,
            "video_id": "",
            "as_json": True,
            "actor": "agent",
            "reason": None,
        },
    )
    assert argv == [
        "pipeline",
        "stage",
        "--project",
        "/tmp/p.json",
        "--stage",
        "sources-ready",
        "--json",
        "--actor",
        "agent",
    ]


def test_strip_mrtr_kwargs_drops_continuity_fields() -> None:
    cleaned = strip_mrtr_kwargs(
        {
            "project": "/tmp/p.json",
            "requestState": "opaque",
            "inputResponses": {"confirm_destructive": {"action": "accept"}},
            "request_state": "snake",
            "input_responses": {},
            "ctx": object(),
            "as_json": True,
        }
    )
    assert cleaned == {"project": "/tmp/p.json", "as_json": True}


def test_run_bridged_strips_mrtr_before_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    def _fake_main(argv: list[str]):
        captured.append(list(argv))
        return 0

    monkeypatch.setattr("avo.cli.main", _fake_main)
    result = run_bridged(
        ("cleanup", "verify"),
        {
            "project": "/tmp/p.json",
            "as_json": True,
            "requestState": "must-not-become-flag",
            "inputResponses": {"k": {"action": "accept"}},
        },
    )
    assert result.ok is True
    assert captured == [["cleanup", "verify", "--project", "/tmp/p.json", "--json"]]
    joined = " ".join(captured[0])
    assert "requestState" not in joined
    assert "inputResponses" not in joined


def test_kwargs_to_argv_repeats_list_flags() -> None:
    argv = kwargs_to_argv(
        ("sync", "inventory"),
        {"project": "p.json", "source": ["a.mov", "b.wav"], "as_json": False},
    )
    assert argv == [
        "sync",
        "inventory",
        "--project",
        "p.json",
        "--source",
        "a.mov",
        "--source",
        "b.wav",
    ]


def test_kwargs_to_argv_kebab_and_recovery_event() -> None:
    argv = kwargs_to_argv(
        ("pipeline", "resume"),
        {
            "project": "p.json",
            "actor": "a",
            "reason": "r",
            "recovery_event": "evt-1",
            "as_json": True,
        },
    )
    assert "--recovery-event" in argv
    assert argv[argv.index("--recovery-event") + 1] == "evt-1"
    assert "--json" in argv


def test_kwargs_to_argv_migrate_timeline_and_cleanup() -> None:
    migrate = kwargs_to_argv(
        ("migrate-timeline", "activate"),
        {
            "project": "p.json",
            "edl": "edl.json",
            "actor": "agent",
            "reason": "cutover",
            "confirm_unknown_approvals": True,
            "as_json": True,
        },
    )
    assert migrate[:2] == ["migrate-timeline", "activate"]
    assert "--edl" in migrate
    assert "--confirm-unknown-approvals" in migrate
    assert "--json" in migrate

    cleanup = kwargs_to_argv(
        ("cleanup", "execute"),
        {
            "project": "p.json",
            "master_basename": "master-v001",
            "session_id": "sess-1",
            "as_json": True,
        },
    )
    assert cleanup[:2] == ["cleanup", "execute"]
    assert "--master-basename" in cleanup
    assert cleanup[cleanup.index("--master-basename") + 1] == "master-v001"
    assert "--session-id" in cleanup


def test_run_cli_pipeline_status_on_tmp_project(tmp_path: Path) -> None:
    project = _project(tmp_path)
    init = run_cli(["pipeline", "run", "--project", str(project), "--json"])
    assert init.ok is True
    result = run_bridged(
        ("pipeline", "status"),
        {"project": str(project), "as_json": True},
    )
    assert result.ok is True
    assert result.exit_code == 0
    assert result.parsed_json is not None
    assert "pipeline" in result.parsed_json
    envelope = result.to_dict()
    assert envelope["ok"] is True
    assert envelope["parsed_json"]["pipeline"]["mainState"]


def test_run_cli_argparse_failure_envelope() -> None:
    result = run_cli(["pipeline"])
    assert result.ok is False
    assert result.exit_code != 0


def test_remaining_group_argparse_failures_use_envelope() -> None:
    """Missing required args for remaining groups → failed envelope (no providers)."""
    for argv in (
        ["bmap", "status"],  # missing --project
        ["cleanup", "execute"],  # missing --project / --master-basename
        ["migrate-timeline", "activate"],  # missing required flags
        ["review", "run"],  # missing --project
    ):
        result = run_cli(list(argv))
        assert result.ok is False
        assert result.exit_code != 0


def test_bridge_does_not_leak_cli_stdout(tmp_path: Path) -> None:
    project = _project(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        run_cli(["pipeline", "run", "--project", str(project), "--json"])
    assert buf.getvalue() == ""


def test_cli_tool_specs_cover_all_groups() -> None:
    specs = cli_tool_specs()
    assert specs
    groups = {s.group for s in specs}
    assert groups == set(ALL_CLI_GROUPS)
    assert set(CORE_CLI_GROUPS).issubset(groups)
    assert set(REMAINING_CLI_GROUPS).issubset(groups)
    names = tool_names(build_registry())
    assert "avo_health" in names
    assert "avo_pipeline_status" in names
    assert "avo_timeline_init" in names
    assert "avo_sync_inventory" in names
    assert "avo_animation_author" in names
    assert "avo_tracks_inspect" in names
    assert "avo_bmap_status" in names
    assert "avo_cmap_project" in names
    assert "avo_review_run" in names
    assert "avo_deliver_validate" in names
    assert "avo_migrate_timeline_inspect" in names
    assert "avo_cleanup_dry_run" in names
    assert "avo_cleanup_execute" in names


def test_destructive_flags_and_warnings() -> None:
    status = get_tool("avo_pipeline_status")
    assert status is not None
    assert status.destructive is False

    stage = get_tool("avo_pipeline_stage")
    assert stage is not None
    assert stage.destructive is True
    assert "WARNING" in stage.description

    render = get_tool("avo_tracks_render")
    assert render is not None
    assert render.destructive is True
    assert "WARNING" in render.description

    cleanup_execute = get_tool("avo_cleanup_execute")
    assert cleanup_execute is not None
    assert cleanup_execute.destructive is True
    assert "DESTRUCTIVE" in cleanup_execute.description

    migrate_activate = get_tool("avo_migrate_timeline_activate")
    assert migrate_activate is not None
    assert migrate_activate.destructive is True
    assert "DESTRUCTIVE" in migrate_activate.description

    migrate_rollback = get_tool("avo_migrate_timeline_rollback")
    assert migrate_rollback is not None
    assert migrate_rollback.destructive is True
    assert "DESTRUCTIVE" in migrate_rollback.description


def test_kwargs_to_argv_omits_false_bools() -> None:
    argv = kwargs_to_argv(
        ("migrate-timeline", "activate"),
        {
            "project": "p.json",
            "edl": "edl.json",
            "confirm_unknown_approvals": False,
            "as_json": False,
        },
    )
    assert "--confirm-unknown-approvals" not in argv
    assert "--json" not in argv


def test_bridge_envelope_keys_always_present() -> None:
    result = run_cli(["pipeline"])  # argparse failure
    envelope = result.to_dict()
    assert set(envelope) == {"ok", "exit_code", "stdout", "stderr", "parsed_json"}
    assert envelope["ok"] is False
    assert envelope["parsed_json"] is None


def test_bridge_non_json_stdout_leaves_parsed_json_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def prose(_argv: list[str]) -> int:
        print("not json output from cli")
        return 0

    monkeypatch.setattr("avo.cli.main", prose)
    result = run_cli(["pipeline", "status", "--project", "unused.json"])
    assert result.ok is True
    assert "not json output from cli" in result.stdout
    assert result.parsed_json is None


def test_bridge_parses_json_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    def emit_json(_argv: list[str]) -> int:
        print(json.dumps({"ok": True, "source": "bridge-test"}))
        return 0

    monkeypatch.setattr("avo.cli.main", emit_json)
    result = run_cli(["pipeline", "status", "--project", "unused.json"])
    assert result.ok is True
    assert result.parsed_json == {"ok": True, "source": "bridge-test"}
    assert result.to_dict()["parsed_json"]["source"] == "bridge-test"


def test_bridge_unexpected_exception_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_argv: list[str]) -> int:
        raise RuntimeError("synthetic bridge failure")

    monkeypatch.setattr("avo.cli.main", boom)
    result = run_cli(["pipeline", "status", "--project", "unused.json"])
    assert result.ok is False
    assert result.exit_code == 1
    assert "RuntimeError" in result.stderr
    assert "synthetic bridge failure" in result.stderr


def test_tmp_project_fixture_stays_under_tmp_path(tmp_path: Path) -> None:
    """Bridge integration must use synthetic tmp projects — never real providers/footage."""
    project = _project(tmp_path)
    assert project.is_relative_to(tmp_path)
    payload = json.loads(project.read_text(encoding="utf-8"))
    raw_dir = Path(payload["rawDir"])
    assert raw_dir.is_relative_to(tmp_path)
    assert "providers/" not in str(project)
    assert "providers/" not in str(raw_dir)


def test_cli_argv_templates_match_prefixes() -> None:
    for defn in all_bridge_defs():
        assert defn.spec.cli_argv_template == defn.cli_prefix
        prefix = f"avo_{defn.spec.group.replace('-', '_')}_"
        assert defn.spec.name.startswith(prefix)


def test_remaining_bridge_defs_match_cli_groups() -> None:
    remaining = remaining_bridge_defs()
    assert remaining
    assert {d.spec.group for d in remaining} == set(REMAINING_CLI_GROUPS)
    # Core defs still available separately
    assert {d.spec.group for d in core_bridge_defs()} == set(CORE_CLI_GROUPS)


def test_register_cli_tools_on_server() -> None:
    pytest.importorskip("mcp")
    import asyncio

    from avo.mcp.server import create_server

    server = create_server()
    tools = asyncio.run(server.list_tools())
    by_name = {t.name: t for t in tools}
    assert "avo_pipeline_status" in by_name
    assert "avo_timeline_status" in by_name
    assert "avo_bmap_status" in by_name
    assert "avo_cleanup_execute" in by_name
    assert "avo_migrate_timeline_activate" in by_name
    schema = by_name["avo_pipeline_status"].input_schema
    assert "project" in schema.get("properties", {})
    assert "project" in schema.get("required", [])
    cleanup_schema = by_name["avo_cleanup_execute"].input_schema
    assert "master_basename" in cleanup_schema.get("properties", {})
    # Empty register is a no-op
    assert register_cli_tools(server, specs=[]) == []


def test_capabilities_lists_all_cli_tools() -> None:
    from avo.mcp.tools.meta import capabilities_payload

    caps = capabilities_payload()
    names = {t["name"] for t in caps["tools"]}
    assert "avo_pipeline_status" in names
    assert "avo_bmap_status" in names
    assert "avo_cleanup_execute" in names
    assert "pipeline" in caps["groups"]
    assert "timeline" in caps["groups"]
    assert "cleanup" in caps["groups"]
    assert "migrate-timeline" in caps["groups"]
    assert caps["docs"] == "docs/avo-mcp.md"
