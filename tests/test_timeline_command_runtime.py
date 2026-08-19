from __future__ import annotations

from pathlib import Path

import pytest

from avo.timeline.command_registry import (
    COMMANDS,
    CommandPermissionError,
    authorize,
    registry_document,
)


def test_all_command_wrappers_have_exactly_one_runtime_mode():
    wrappers = {path.stem for path in Path("commands/avo").glob("*.md")}
    assert len(wrappers) == 51
    assert wrappers == set(COMMANDS)
    assert len(registry_document()["commands"]) == 51
    assert all(
        spec.mode in {"Owns", "Evidence", "Consumes", "Profile", "Admin"}
        for spec in COMMANDS.values()
    )
    for name, spec in COMMANDS.items():
        text = (Path("commands/avo") / f"{name}.md").read_text(encoding="utf-8")
        assert f"**Timeline integration:** {spec.mode}" in text
        assert "Shared timeline gateway" in text or name in {"pipeline"}


@pytest.mark.parametrize(
    "name", ["chapters", "deliver", "retention", "thumbnail", "cleanup", "stats"]
)
def test_read_only_and_admin_commands_cannot_mutate(name):
    with pytest.raises(CommandPermissionError):
        authorize(name, mutation="cmap")


def test_evidence_commands_can_write_evidence_but_not_maps():
    authorize("watch", writes_evidence=True)
    with pytest.raises(CommandPermissionError):
        authorize("watch", mutation="bmap")


def test_owner_permissions_are_artifact_scoped():
    authorize("trim", mutation="cmap")
    authorize("sound", mutation="tracks")
    with pytest.raises(CommandPermissionError):
        authorize("trim", mutation="tracks")
    with pytest.raises(CommandPermissionError):
        authorize("sound", mutation="sync-map")


def test_profile_requires_isolated_child_lineage():
    with pytest.raises(CommandPermissionError):
        authorize("talking-head", target_scope="current")
    authorize(
        "talking-head",
        target_scope="child",
        parent_timeline_ref="parent:cmap-r0007:sha256",
    )
