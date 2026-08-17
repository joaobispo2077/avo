from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.sync import SyncError
from avo.timeline.sync_service import SyncService
from avo.timeline.workspace import TimelineWorkspace

SHA = "a" * 64


def project(tmp_path: Path) -> TimelineWorkspace:
    raw = tmp_path / "raw"
    raw.mkdir()
    path = raw / "avo.project.json"
    path.write_text(
        json.dumps(
            {
                "provider": "bishop",
                "rawDir": str(raw),
                "timeline": {
                    "directory": "edit/timeline",
                    "reviewDirectory": "edit/review",
                    "generatedEdlPath": "edit/edl.json",
                },
            }
        ),
        encoding="utf-8",
    )
    ws = TimelineWorkspace.from_project(path, video_id="demo")
    ws.initialize()
    return ws


def raw(source_id: str, sha: str) -> dict:
    return {
        "sourceId": source_id,
        "kind": "raw",
        "fingerprint": {"sha256": sha, "sizeBytes": 1},
        "stream": "a:0" if source_id == "mic" else "v:0",
        "channels": [0] if source_id == "mic" else [],
    }


def test_author_validate_and_decide_constant_sync(tmp_path: Path) -> None:
    service = SyncService(project(tmp_path))
    revision = service.author_constant(
        picture=raw("cam", "a" * 64),
        audio=raw("mic", "b" * 64),
        offset_ticks=128,
        timebase={"num": 1, "den": 1000},
        samples=[(0, -128), (5000, 4872), (10000, 9872)],
        tolerance_ticks=20,
        actor="agent",
        reason="calibrate",
    )
    evidence = service.validate_current()
    assert evidence["status"] == "pass" and evidence["coverage"]["windows"] == [
        0,
        5000,
        10000,
    ]
    event = service.decide(
        decision="approved",
        candidate_hash="c" * 64,
        evidence_bundle_hash=evidence["sha256"],
        actor="creator",
        reason="approved",
    )
    assert event["type"] == "approved"
    assert service.store.effective_approval() is not None


def test_not_applicable_requires_current_basis_actor_and_reason(tmp_path: Path) -> None:
    service = SyncService(project(tmp_path))
    with pytest.raises(SyncError):
        service.author_not_applicable(raw_fingerprints={}, actor="", reason="")
    revision = service.author_not_applicable(
        raw_fingerprints={"muxed": "a" * 64}, actor="agent", reason="single muxed clock"
    )
    evidence = service.validate_current()
    assert evidence["status"] == "not-applicable" and evidence["rationale"]
