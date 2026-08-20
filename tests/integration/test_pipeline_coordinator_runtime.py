from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.command_handlers import CommandHandlers
from avo.timeline.command_registry import CommandPermissionError
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.workspace import TimelineWorkspace


def project(tmp_path: Path, name="parent") -> Path:
    path = tmp_path / name / "avo.project.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "bishop",
                "videoId": name,
                "rawDir": str(path.parent),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_persisted_stage_block_resume_and_direct_permissions(tmp_path: Path):
    parent_project = project(tmp_path)
    workspace = TimelineWorkspace.from_project(parent_project)
    pipeline = TimelinePipeline(workspace)
    pipeline.initialize()
    pipeline.advance(
        "sources-ready",
        rawInventory={"sources": [{"sourceId": "raw-one", "sha256": "a" * 64}]},
        actor="avo.pipeline",
        reason="inventory",
    )
    blocked = pipeline.enter_blocked(
        reason="Watch unavailable",
        blockers=[
            {
                "code": "WATCH_UNAVAILABLE",
                "message": "offline",
                "remediation": "install Watch",
            }
        ],
    )
    assert blocked["sideState"] == "blocked"
    resumed = pipeline.resume(
        actor="creator",
        reason="Watch restored",
        recovery_event="watch-install-complete",
    )
    assert resumed["sideState"] is None
    assert resumed["mainState"] == "sources-ready"

    handlers = CommandHandlers(pipeline)
    result = handlers.execute("stats", "status")
    assert result["mutated"] is False
    with pytest.raises(CommandPermissionError):
        handlers.execute("stats", "status", {"mutation": "cmap"})


def test_profile_derivative_cannot_target_parent(tmp_path: Path):
    parent_project = project(tmp_path)
    child_project = project(tmp_path, "child")
    pipeline = TimelinePipeline(TimelineWorkspace.from_project(parent_project))
    pipeline.initialize()
    handlers = CommandHandlers(pipeline)
    with pytest.raises(ValueError, match="cannot mutate parent"):
        handlers.execute(
            "talking-head",
            "run",
            {
                "targetScope": "child",
                "parentTimelineRef": "parent:cmap-r0001:hash",
                "childProject": str(parent_project),
            },
        )
    result = handlers.execute(
        "talking-head",
        "run",
        {
            "targetScope": "child",
            "parentTimelineRef": "parent:cmap-r0001:hash",
            "childProject": str(child_project),
        },
    )
    assert result["childProject"] == str(child_project)
