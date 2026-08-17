from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from avo.timeline.lifecycle import PipelineRunStore
from avo.timeline.lineage import persist_invalidation
from avo.timeline.workspace import TimelineWorkspace

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def make_project(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "provider": "bishop",
                "rawDir": str(raw),
                "timeline": {
                    "directory": "edit/timeline",
                    "reviewDirectory": "edit/review",
                    "generatedEdlPath": "edit/edl.json",
                    "canonicalFirst": True,
                    "migration": {
                        "allowLegacyEdlFallback": True,
                        "warnOnDerivedEdlMismatch": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return project


def cli(project: Path, operation: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "avo.cli",
            "timeline",
            operation,
            "--project",
            str(project),
            "--video-id",
            "demo",
            "--json",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
    )


def test_external_project_runtime_spine_round_trip(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    created = cli(project, "init")
    assert created.returncode == 0, created.stderr
    status = json.loads(cli(project, "status").stdout)
    assert status["authority"] == "canonical"
    ws = TimelineWorkspace.from_project(project, video_id="demo")
    cmap = ws.store("cmap")
    bmap = ws.store("bmap")
    first = cmap.append_revision(snapshot={}, actor="agent", reason="one")
    bmap.append_revision(snapshot={}, actor="agent", reason="beat")
    cmap.record_decision(
        decision="approved",
        revision_id=first["revisionId"],
        revision_hash=first["contentHash"],
        candidate_hash="c" * 64,
        dependency_hashes={"cmap": first["contentHash"]},
        actor="creator",
        checkpoint="cut-proof",
        scope="full",
        reason="approved",
        evidence_bundle_hash="e" * 64,
    )
    second = cmap.append_revision(
        snapshot={},
        actor="agent",
        reason="two",
        expected_head_hash=first["contentHash"],
    )
    report = persist_invalidation(
        {"cmap": cmap, "bmap": bmap},
        "cmap",
        before_hash=first["contentHash"],
        after_hash=second["contentHash"],
        reason="new cut",
    )
    assert report["affected"][0]["artifactType"] == "bmap"
    assert cmap.effective_approval() is None
    assert cli(project, "validate").returncode == 0
    run = PipelineRunStore(ws.pipeline_run_path)
    run.enter_side_state(
        "blocked", actor="agent", reason="tool outage", blockers=[{"code": "WATCH"}]
    )
    resumed = subprocess.run(
        [
            sys.executable,
            "-m",
            "avo.cli",
            "timeline",
            "resume",
            "--project",
            str(project),
            "--video-id",
            "demo",
            "--actor",
            "agent",
            "--reason",
            "tool restored",
            "--recovery-event",
            "watch-installed",
            "--json",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)["sideState"] is None
