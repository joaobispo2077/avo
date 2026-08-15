"""Unit tests for avo.mcp tool registry (no providers / footage)."""
from __future__ import annotations

from pathlib import Path

from avo.mcp.registry import (
    META_CAPABILITIES,
    META_HEALTH,
    PLANNED_CLI_GROUPS,
    PROTOCOL_MRTR,
    PROTOCOL_STATELESS,
    PROTOCOL_TARGET,
    TRANSPORT,
    ToolSpec,
    build_registry,
    cli_tool_specs,
    get_tool,
    meta_tool_specs,
    protocol_posture,
    registered_groups,
    tool_names,
    tools_by_group,
)
from avo.mcp.tools.cli_tools import ALL_CLI_GROUPS, CORE_CLI_GROUPS, REMAINING_CLI_GROUPS


def test_transport_is_stdio() -> None:
    assert TRANSPORT == "stdio"


def test_protocol_posture_constants() -> None:
    assert PROTOCOL_TARGET == "2026-07-28"
    assert PROTOCOL_STATELESS is True
    assert PROTOCOL_MRTR is True
    assert protocol_posture() == {
        "target": "2026-07-28",
        "stateless": True,
        "mrtr": True,
    }


def test_meta_tool_specs_catalog() -> None:
    specs = meta_tool_specs()
    assert [s.name for s in specs] == ["avo_health", "avo_list_capabilities"]
    assert all(s.group == "meta" for s in specs)
    assert all(not s.destructive for s in specs)
    assert META_HEALTH in specs
    assert META_CAPABILITIES in specs


def test_cli_tool_specs_all_planned_groups_registered() -> None:
    """All phase-1 CLI groups (tasks 007–008) are registered."""
    specs = cli_tool_specs()
    assert specs
    groups = {s.group for s in specs}
    assert groups == set(ALL_CLI_GROUPS)
    assert set(PLANNED_CLI_GROUPS) == set(ALL_CLI_GROUPS)
    assert set(CORE_CLI_GROUPS).issubset(groups)
    assert set(REMAINING_CLI_GROUPS).issubset(groups)
    assert "cleanup" in groups
    assert "bmap" in groups
    assert "migrate-timeline" in groups


def test_build_registry_includes_meta_and_all_cli() -> None:
    registry = build_registry()
    names = tool_names(registry)
    assert names[:2] == ["avo_health", "avo_list_capabilities"]
    assert "avo_pipeline_status" in names
    assert "avo_bmap_status" in names
    assert "avo_cleanup_execute" in names
    assert "avo_migrate_timeline_activate" in names
    groups = registered_groups(registry)
    assert groups[0] == "meta"
    assert "pipeline" in groups
    assert "cleanup" in groups

    extra = ToolSpec(
        name="avo_extra_demo",
        description="placeholder",
        group="extra",
        cli_argv_template=("extra", "demo"),
    )
    with_extra = build_registry(extra=[extra])
    assert "avo_extra_demo" in tool_names(with_extra)
    assert tools_by_group("extra", with_extra) == [extra]
    assert get_tool("avo_extra_demo", with_extra) is extra
    assert get_tool("missing", with_extra) is None


def test_registry_lookup_helpers() -> None:
    registry = build_registry()
    assert get_tool("avo_health", registry) is META_HEALTH
    assert tools_by_group("meta", registry) == list(meta_tool_specs())
    assert tools_by_group("pipeline", registry)
    assert tools_by_group("cleanup", registry)
    assert get_tool("avo_pipeline_status", registry) is not None
    assert get_tool("avo_cleanup_execute", registry) is not None


def test_destructive_cleanup_and_migrate_warnings() -> None:
    execute = get_tool("avo_cleanup_execute")
    assert execute is not None
    assert execute.destructive is True
    assert "DESTRUCTIVE" in execute.description

    activate = get_tool("avo_migrate_timeline_activate")
    assert activate is not None
    assert activate.destructive is True
    assert "DESTRUCTIVE" in activate.description

    rollback = get_tool("avo_migrate_timeline_rollback")
    assert rollback is not None
    assert rollback.destructive is True
    assert "DESTRUCTIVE" in rollback.description


def test_tool_names_are_unique() -> None:
    names = tool_names(build_registry())
    assert len(names) == len(set(names))


def test_every_cli_group_has_at_least_one_tool() -> None:
    registry = build_registry()
    for group in ALL_CLI_GROUPS:
        assert tools_by_group(group, registry), f"missing tools for group {group!r}"


def test_destructive_cutover_tools_are_exactly_flagged() -> None:
    """cleanup execute + migrate activate/rollback must carry DESTRUCTIVE warning."""
    registry = build_registry()
    cutover = {
        "avo_cleanup_execute",
        "avo_migrate_timeline_activate",
        "avo_migrate_timeline_rollback",
    }
    for name in cutover:
        spec = get_tool(name, registry)
        assert spec is not None, name
        assert spec.destructive is True, name
        assert "DESTRUCTIVE" in spec.description, name

    # Safer siblings stay non-cutover (no DESTRUCTIVE banner).
    dry_run = get_tool("avo_cleanup_dry_run", registry)
    assert dry_run is not None
    assert dry_run.destructive is False
    assert "DESTRUCTIVE" not in dry_run.description

    inspect = get_tool("avo_migrate_timeline_inspect", registry)
    assert inspect is not None
    assert inspect.destructive is False
    assert "DESTRUCTIVE" not in inspect.description


def test_registry_module_has_no_provider_or_footage_imports() -> None:
    """Registry catalog must stay pure data — no providers/*/footage coupling."""
    import avo.mcp.registry as registry_mod

    source = Path(registry_mod.__file__).read_text(encoding="utf-8")
    assert "providers/" not in source
    assert "footage" not in source.lower()
