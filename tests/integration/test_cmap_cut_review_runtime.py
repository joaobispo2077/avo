from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.adapters.qc.cut_proof import CutProofQcAdapter
from avo.timeline.approval_service import ApprovalService
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.materialize import materialize_cut_proof
from avo.timeline.review_runner import ReviewRunner
from avo.timeline.sync_service import SyncService
from avo.timeline.workspace import TimelineWorkspace

from tests.fixtures.timeline.build_fixtures import build_fixture_set
from tests.test_timeline_review_integration import FakeTranscript, FakeWatch


def _time(ticks: int, source_id: str) -> dict:
    return {
        "ticks": ticks,
        "timebase": {"num": 1, "den": 1000},
        "domain": "raw-source",
        "sourceId": source_id,
    }


def _snapshot(source_a: Path, source_b: Path, *, second: bool) -> dict:
    sources = [
        {
            "sourceId": "source-a",
            "kind": "raw",
            "locator": str(source_a),
            "fingerprint": file_fingerprint(source_a),
        },
        {
            "sourceId": "source-b",
            "kind": "raw",
            "locator": str(source_b),
            "fingerprint": file_fingerprint(source_b),
        },
    ]
    if second:
        definitions = [
            ("segment-b", "source-b", 250, 1250),
            ("segment-a", "source-a", 500, 1500),
        ]
    else:
        definitions = [
            ("segment-a", "source-a", 0, 1500),
            ("segment-b", "source-b", 0, 1500),
        ]
    return {
        "sources": sources,
        "segments": [
            {
                "segmentId": segment_id,
                "sourceId": source_id,
                "in": _time(start, source_id),
                "out": _time(end, source_id),
                "reason": "preserve the source statement",
            }
            for segment_id, source_id, start, end in definitions
        ],
    }


def _workspace(raw_dir: Path) -> TimelineWorkspace:
    project_path = raw_dir / "avo.project.json"
    project_path.write_text(
        json.dumps(
            {
                "provider": "bishop",
                "rawDir": str(raw_dir),
                "videoId": "timeline-cut",
                "timeline": {
                    "directory": "edit/timeline",
                    "reviewDirectory": "edit/review",
                    "generatedEdlPath": "edit/edl.json",
                },
            }
        ),
        encoding="utf-8",
    )
    workspace = TimelineWorkspace.from_project(project_path)
    workspace.initialize()
    return workspace


def _review(workspace: TimelineWorkspace, revision: dict, materialization: dict) -> dict:
    return ReviewRunner(
        review_root=workspace.review_dir,
        transcription=FakeTranscript(),
        watch=FakeWatch(),
        deterministic_qc=CutProofQcAdapter(),
        workspace=workspace,
        clock=lambda: "2026-08-13T00:00:00Z",
    ).run(
        checkpoint="cut-proof",
        candidate=Path(materialization["output"]["locator"]),
        dependencies={
            "cmap": revision["contentHash"],
            "sync-map": revision["snapshot"]["syncRef"]["contentSha256"],
            "cutOutput": materialization["output"]["sha256"],
        },
        render_profile="draft",
    )


def test_multi_source_raw_cmap_to_exact_current_approval(tmp_path: Path) -> None:
    raw_dir = tmp_path / "project"
    raw_dir.mkdir()
    build_fixture_set(raw_dir)
    source_a = raw_dir / "source-a.mp4"
    source_b = raw_dir / "source-b.mp4"
    workspace = _workspace(raw_dir)

    sync = SyncService(workspace)
    sync_revision = sync.author_not_applicable(
        raw_fingerprints={
            "source-a": file_fingerprint(source_a)["sha256"],
            "source-b": file_fingerprint(source_b)["sha256"],
        },
        actor="avo",
        reason="both sources contain picture and audio on one embedded clock",
    )
    sync_evidence = sync.validate_current()
    sync.decide(
        decision="approved",
        candidate_hash=sync_revision["contentHash"],
        evidence_bundle_hash=sync_evidence["sha256"],
        actor="creator",
        reason="embedded clocks approved",
    )

    cmap = CMapService(workspace)
    first = cmap.author(
        _snapshot(source_a, source_b, second=False),
        actor="avo",
        reason="first cut",
    )
    first_materialization = materialize_cut_proof(
        workspace=workspace,
        cmap_revision_id=first["revisionId"],
        output_path=raw_dir / "edit" / "cut-proof-r1.mp4",
    )
    first_review = _review(workspace, first, first_materialization)
    assert first_review["state"] == "ai-passed"

    second = cmap.author(
        _snapshot(source_a, source_b, second=True),
        actor="avo",
        reason="reordered tighter cut from raw",
    )
    second_materialization = materialize_cut_proof(
        workspace=workspace,
        cmap_revision_id=second["revisionId"],
        output_path=raw_dir / "edit" / "cut-proof-r2.mp4",
    )
    second_review = _review(workspace, second, second_materialization)
    assert second_review["state"] == "ai-passed"
    assert Path(second_materialization["output"]["locator"]).is_file()

    with pytest.raises(ValueError, match="current"):
        ApprovalService(workspace).decide(
            decision="approved",
            revision_id=first["revisionId"],
            review_path=first_review["reviewPath"],
            materialization_path=workspace.timeline_dir / "materializations" / "cut-proof" / f"{first_materialization['materializationId']}.json",
            actor="creator",
            reason="old proof must not approve",
        )

    event = ApprovalService(workspace).decide(
        decision="approved",
        revision_id=second["revisionId"],
        review_path=second_review["reviewPath"],
        materialization_path=workspace.timeline_dir / "materializations" / "cut-proof" / f"{second_materialization['materializationId']}.json",
        actor="creator",
        reason="approve exact current cut",
    )
    assert workspace.store("cmap").effective_approval()["eventId"] == event["eventId"]

    derived = _snapshot(source_a, source_b, second=True)
    derived["sources"][0] = {
        "sourceId": "source-a",
        "kind": "raw",
        "locator": second_materialization["output"]["locator"],
        "fingerprint": file_fingerprint(Path(second_materialization["output"]["locator"])),
    }
    with pytest.raises(Exception, match="derived|edit"):
        cmap.author(derived, actor="avo", reason="must reject proof as source")
