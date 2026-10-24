"""The artistic intake surface owns no canonical video mutations."""

import ast
from pathlib import Path

import pytest

from avo.timeline.command_registry import (
    CommandPermissionError,
    authorize,
    command_spec,
)


@pytest.mark.parametrize("name", ["direction", "briefstart"])
def test_artistic_intake_is_admin_without_timeline_ownership(name):
    spec = command_spec(name)
    assert spec.mode == "Admin"
    assert not spec.owns
    assert authorize(name) == spec
    for artifact in ("cmap", "sync-map", "bmap", "tracks", "animation"):
        with pytest.raises(CommandPermissionError):
            authorize(name, mutation=artifact)
    with pytest.raises(CommandPermissionError):
        authorize(name, writes_evidence=True)


def test_direction_domain_has_no_cli_model_or_media_adapter_import():
    base = Path(__file__).parents[1] / "src/avo/direction"
    forbidden = (
        "avo.cli",
        "avo.direction_cli",
        "avo.mcp",
        "avo.adapters",
        "avo.proof_composition",
    )
    for path in base.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [x.name for x in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            assert not any(
                m == f or m.startswith(f + ".") for m in modules for f in forbidden
            ), path
