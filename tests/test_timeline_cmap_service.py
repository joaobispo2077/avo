from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.lineage import LineageError
from avo.timeline.sync_service import SyncService
from avo.timeline.workspace import TimelineWorkspace


def workspace(tmp_path: Path) -> TimelineWorkspace:
    raw = tmp_path / "project"
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
                },
            }
        ),
        encoding="utf-8",
    )
    ws = TimelineWorkspace.from_project(project, video_id="demo")
    ws.initialize()
    sync = SyncService(ws)
    rev = sync.author_not_applicable(
        raw_fingerprints={"muxed": "a" * 64}, actor="agent", reason="single muxed clock"
    )
    ev = sync.validate_current()
    sync.decide(
        decision="approved",
        candidate_hash=rev["contentHash"],
        evidence_bundle_hash=ev["sha256"],
        actor="creator",
        reason="approved",
    )
    return ws


def snapshot(
    path: Path,
    *,
    segment_id: str = "segment-one",
    start: int = 0,
    end: int = 1000,
    kind: str = "raw",
) -> dict:
    fp = file_fingerprint(path)
    return {
        "sources": [
            {
                "sourceId": "camera",
                "kind": kind,
                "locator": str(path),
                "fingerprint": fp,
            }
        ],
        "segments": [
            {
                "segmentId": segment_id,
                "sourceId": "camera",
                "in": {
                    "ticks": start,
                    "timebase": {"num": 1, "den": 1000},
                    "domain": "raw-source",
                    "sourceId": "camera",
                },
                "out": {
                    "ticks": end,
                    "timebase": {"num": 1, "den": 1000},
                    "domain": "raw-source",
                    "sourceId": "camera",
                },
                "reason": "keep meaning",
            }
        ],
    }


def test_authors_raw_revision_with_sync_basis_and_replayable_diff(
    tmp_path: Path,
) -> None:
    ws = workspace(tmp_path)
    raw = ws.raw_dir / "raw.bin"
    raw.write_bytes(b"raw")
    service = CMapService(ws)
    first = service.author(snapshot(raw), actor="agent", reason="first")
    assert first["snapshot"]["syncRef"]["artifactType"] == "sync-map"
    assert first["diff"][0]["op"] == "add"
    second = service.author(
        snapshot(raw, start=100, end=900), actor="agent", reason="trim"
    )
    assert any(
        item["op"] == "replace" and item["target"]["stableId"] == "segment-one"
        for item in second["diff"]
    )
    assert (
        service.store.revision(first["revisionId"])["snapshot"]["segments"][0]["in"][
            "ticks"
        ]
        == 0
    )


def test_rejects_derived_or_changed_raw_source(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    raw = ws.raw_dir / "raw.bin"
    raw.write_bytes(b"raw")
    service = CMapService(ws)
    with pytest.raises(LineageError):
        service.author(snapshot(raw, kind="proxy"), actor="agent", reason="bad")
    value = snapshot(raw)
    raw.write_bytes(b"changed")
    with pytest.raises(LineageError, match="fingerprint mismatch"):
        service.author(value, actor="agent", reason="bad")
