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


@pytest.mark.integration
def test_pipeline_materializes_real_code_drawn_source_using_only_injected_adapter(
    tmp_path, monkeypatch
):
    import json
    import os
    import subprocess

    import numpy as np
    from tests.test_timeline_animation_service import code_drawn_workspace

    from avo import motion
    from avo.adapters.motion.code_drawn import CodeDrawnAdapter, runtime_readiness
    from avo.timeline.contracts import file_fingerprint
    from avo.timeline.generated_assets import GeneratedAssetService

    readiness = runtime_readiness()
    if not readiness["ready"]:
        reason = "; ".join(str(value) for value in readiness["blockers"])
        if os.environ.get("AVO_REQUIRE_CODE_DRAWN_RUNTIME") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    workspace, _, reference = code_drawn_workspace(tmp_path)
    before = workspace.active_dependency_snapshot()
    cut_approval = workspace.store("cmap").effective_approval()

    def no_framework(*args, **kwargs):
        pytest.fail("Code-drawn canonical generation loaded HyperFrames.")

    monkeypatch.setattr(
        "avo.adapters.motion.hyperframes.HyperframesAdapter", no_framework
    )
    adapter = CodeDrawnAdapter()

    def materializer(workspace, instance_id, *, output):
        return motion.materialize_code_drawn(
            workspace, instance_id, output=output, adapter=adapter
        )

    pipeline = TimelinePipeline(workspace, motion_materializer=materializer)
    state = pipeline.run_store.load()
    output = workspace.raw_dir / "edit/derived/instance-overlay.mkv"
    result = pipeline.materialize_motion(reference["instanceId"], output=output)
    assert result["status"] == "ok"
    assert output.is_file()
    receipt_path = output.with_suffix(".generated-asset.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["generator"]["adapterId"] == "code-drawn"
    assert receipt["parameters"]["codeDrawn"]["instanceId"] == reference["instanceId"]
    locked = receipt["parameters"]["codeDrawn"]["canonicalInputLock"]
    assert all(locked[key] == value for key, value in before.items())
    assert (
        GeneratedAssetService(workspace).load(receipt["assetId"])["recordHash"]
        == receipt["recordHash"]
    )
    assert receipt["output"]["sha256"] == file_fingerprint(output)["sha256"]
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(output),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    pixels = np.frombuffer(raw, np.uint8).reshape(-1, 96, 128, 4)
    assert len(pixels) == 9
    assert np.any(pixels[:, :, :, 3] == 0)
    assert np.any(pixels[:, :, :, 3] > 0)
    assert workspace.active_dependency_snapshot() == before
    assert workspace.store("cmap").effective_approval() == cut_approval
    assert pipeline.run_store.load()["mainState"] == state["mainState"]
    # Source-free drawing was rendered physically; this fixture does not claim
    # to decode its separate synthetic approval fixture's raw.bin footage.
