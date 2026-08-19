from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.contracts import file_fingerprint
from avo.timeline.migration import MigrationService
from avo.timeline.workspace import TimelineWorkspace


def fixture(tmp_path: Path, *, missing_source=False):
    raw = tmp_path / "raw.mp4"
    if not missing_source:
        raw.write_bytes(b"legacy-raw")
    overlay = tmp_path / "insert.png"
    overlay.write_bytes(b"image")
    edl = tmp_path / "edl.json"
    edl.write_text(
        json.dumps(
            {
                "version": 4,
                "story_map_approval": "approved",
                "sources": {"camera": "raw.mp4"},
                "ranges": [
                    {"source": "camera", "start": 0.0, "end": 2.0},
                    {"source": "camera", "start": 3.0, "end": 5.0},
                ],
                "overlays": [
                    {
                        "file": "insert.png",
                        "start_in_output": 1.0,
                        "duration": 0.5,
                        "motion_brief_id": "legacy-insert",
                    }
                ],
                "sound_effects": [
                    {
                        "file": "pop.mp3",
                        "start_in_output": 2.5,
                        "duration": 0.2,
                    }
                ],
                "subtitles": "captions.srt",
                "audio": {"restoration_default_pct": 45},
                "motion_policy": {"style": "tremble"},
            }
        ),
        encoding="utf-8",
    )
    project = tmp_path / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "bishop",
                "videoId": "legacy-video",
                "rawDir": str(tmp_path),
                "timeline": {
                    "directory": "edit/timeline",
                    "reviewDirectory": "edit/review",
                    "generatedEdlPath": "edit/edl.json",
                    "canonicalFirst": False,
                    "migration": {"allowLegacyEdlFallback": True},
                },
            }
        ),
        encoding="utf-8",
    )
    return TimelineWorkspace.from_project(project), edl, project


def test_dry_run_writes_nothing_and_imports_all_domains(tmp_path: Path):
    workspace, edl, _ = fixture(tmp_path)
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    plan = MigrationService(workspace, edl).plan()
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert before == after
    assert set(plan["snapshots"]) == {"cmap", "bmap", "tracks", "animation", "sync-map"}
    assert plan["approvalStatus"] == "unknown"
    assert plan["snapshots"]["bmap"]["cues"]


def test_apply_validate_activate_rollback_is_idempotent_and_preserves_legacy(
    tmp_path: Path,
):
    workspace, edl, project = fixture(tmp_path)
    original = file_fingerprint(edl)["sha256"]
    service = MigrationService(workspace, edl)
    applied = service.apply(actor="creator", reason="migrate legacy project")
    assert applied["status"] == "applied-unverified"
    assert file_fingerprint(edl)["sha256"] == original
    assert service.apply(actor="creator", reason="rerun")["idempotent"] is True
    validated = service.validate(actor="creator", reason="parity accepted")
    assert validated["parity"]["rangesEqual"] is True
    with pytest.raises(ValueError, match="confirmation"):
        service.activate(
            actor="creator", reason="activate", confirm_unknown_approvals=False
        )
    active = service.activate(
        actor="creator",
        reason="approvals remain pending",
        confirm_unknown_approvals=True,
    )
    assert active["authority"] == "canonical"
    stored_project = json.loads(project.read_text(encoding="utf-8"))
    assert stored_project["timeline"]["migration"]["allowLegacyEdlFallback"] is False
    rolled = service.rollback(actor="creator", reason="test recovery")
    assert rolled["status"] == "rolled-back"
    assert file_fingerprint(edl)["sha256"] == original
    assert all(
        (workspace.timeline_dir / f"{kind}.json").is_file()
        for kind in ("cmap", "bmap", "tracks", "animation", "sync-map")
    )


def test_unresolved_source_and_target_collision_block(tmp_path: Path):
    workspace, edl, _ = fixture(tmp_path, missing_source=True)
    service = MigrationService(workspace, edl)
    service.apply(actor="creator", reason="assess unresolved")
    with pytest.raises(ValueError, match="parity"):
        service.validate(actor="creator", reason="must block")

    other = tmp_path / "other"
    other.mkdir()
    workspace2, edl2, _ = fixture(other)
    workspace2.initialize()
    workspace2.store("cmap").append_revision(
        snapshot={"existing": True},
        actor="agent",
        reason="existing",
    )
    with pytest.raises(ValueError, match="collision"):
        MigrationService(workspace2, edl2).apply(actor="creator", reason="collision")
