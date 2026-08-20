"""Unit tests for avo.mcp meta tools (health / capabilities; no project)."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from avo.mcp import DOCS_POINTER, SERVER_NAME
from avo.mcp.registry import (
    PLANNED_CLI_GROUPS,
    PROTOCOL_MRTR,
    PROTOCOL_STATELESS,
    PROTOCOL_TARGET,
    ToolSpec,
    build_registry,
    protocol_posture,
)
from avo.mcp.tools.meta import capabilities_payload, health_payload


def test_health_payload_ok_version_transport() -> None:
    health = health_payload()
    assert health["ok"] is True
    assert health["name"] == SERVER_NAME
    assert isinstance(health["version"], str)
    assert health["version"]
    assert health["transport"] == "stdio"
    # Meta smoke must not require project / provider fields.
    assert "project" not in health
    assert "provider" not in health
    # FR-14 / NFR-9: protocol posture (no secrets).
    assert health["protocol"] == protocol_posture()
    assert health["protocol"] == {
        "target": PROTOCOL_TARGET,
        "stateless": PROTOCOL_STATELESS,
        "mrtr": PROTOCOL_MRTR,
    }
    assert health["protocol"]["target"] == "2026-07-28"
    assert health["protocol"]["stateless"] is True
    assert health["protocol"]["mrtr"] is True
    assert "secret" not in health
    assert "token" not in health
    assert "key" not in health


def test_capabilities_lists_tools_groups_and_docs() -> None:
    caps = capabilities_payload()
    assert caps["ok"] is True
    assert caps["name"] == SERVER_NAME
    assert caps["transport"] == "stdio"
    assert caps["protocol"] == protocol_posture()
    assert caps["docs"] == DOCS_POINTER
    assert caps["docs"] == "docs/avo-mcp.md"
    assert "meta" in caps["groups"]
    assert "pipeline" in caps["groups"]
    assert "cleanup" in caps["groups"]
    assert "bmap" in caps["groups"]
    assert caps["planned_cli_groups"] == list(PLANNED_CLI_GROUPS)
    names = {t["name"] for t in caps["tools"]}
    assert "avo_health" in names
    assert "avo_list_capabilities" in names
    assert "avo_pipeline_status" in names
    assert "avo_cleanup_execute" in names
    assert "avo_migrate_timeline_activate" in names
    meta_tools = [t for t in caps["tools"] if t["group"] == "meta"]
    assert len(meta_tools) == 2
    for tool in meta_tools:
        assert tool["destructive"] is False
        assert "mrtr_gated" not in tool
        assert tool["description"]


def test_capabilities_group_filter() -> None:
    extra = ToolSpec(
        name="avo_demo_extra",
        description="demo extra",
        group="demo",
    )
    registry = build_registry(extra=[extra])
    filtered = capabilities_payload(group="demo", registry=registry)
    assert [t["name"] for t in filtered["tools"]] == ["avo_demo_extra"]
    assert filtered["groups"] == ["demo"]

    meta_only = capabilities_payload(group="meta", registry=registry)
    assert {t["name"] for t in meta_only["tools"]} == {
        "avo_health",
        "avo_list_capabilities",
    }


def test_meta_payloads_produce_no_stdout() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        health_payload()
        capabilities_payload()
    assert buf.getvalue() == ""


def test_registered_meta_tools_on_server() -> None:
    pytest.importorskip("mcp")
    import asyncio

    from avo.mcp.server import create_server

    server = create_server()
    tools = asyncio.run(server.list_tools())
    by_name = {t.name: t for t in tools}
    assert "avo_health" in by_name
    assert "avo_list_capabilities" in by_name
    health_desc = (by_name["avo_health"].description or "").lower()
    assert "project" in health_desc  # states it does not require --project
    caps_desc = (by_name["avo_list_capabilities"].description or "").lower()
    assert "docs" in caps_desc


def test_capabilities_include_every_planned_cli_group() -> None:
    caps = capabilities_payload()
    for group in PLANNED_CLI_GROUPS:
        assert group in caps["groups"], group
        assert any(t["group"] == group for t in caps["tools"]), group


def test_capabilities_surface_destructive_cutover_flags() -> None:
    caps = capabilities_payload()
    by_name = {t["name"]: t for t in caps["tools"]}
    for name in (
        "avo_cleanup_execute",
        "avo_migrate_timeline_activate",
        "avo_migrate_timeline_rollback",
    ):
        assert by_name[name]["destructive"] is True
        assert by_name[name]["mrtr_gated"] is True
        assert "DESTRUCTIVE" in by_name[name]["description"]


def test_capabilities_mrtr_gated_only_on_destructive() -> None:
    caps = capabilities_payload()
    for tool in caps["tools"]:
        if tool["destructive"]:
            assert tool.get("mrtr_gated") is True
        else:
            assert "mrtr_gated" not in tool


def test_meta_tools_need_no_providers_or_footage(tmp_path, monkeypatch) -> None:
    """Health/capabilities must work with cwd isolated from providers/footage trees."""
    monkeypatch.chdir(tmp_path)
    # Ensure a bare cwd without providers/ or footage roots still succeeds.
    assert not (tmp_path / "providers").exists()
    health = health_payload()
    caps = capabilities_payload()
    assert health["ok"] is True
    assert health["protocol"]["mrtr"] is True
    assert caps["ok"] is True
    assert caps["protocol"] == health["protocol"]
    assert caps["docs"] == DOCS_POINTER
    assert "project" not in health
    assert "project" not in caps
