from __future__ import annotations

from pathlib import Path

import pytest

from avo.timeline.approval_service import ApprovalService
from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.lineage import LineageError
from tests.test_timeline_approval_service import approved_review
from tests.test_timeline_cmap_service import snapshot


def approved_workspace(tmp_path: Path):
    workspace, revision, review, materialization = approved_review(tmp_path)
    ApprovalService(workspace).decide(
        decision="approved",
        revision_id=revision["revisionId"],
        review_path=review["reviewPath"],
        materialization_path=materialization,
        actor="creator",
        reason="approve cut",
    )
    return workspace, revision, review["candidate"]["sha256"]


def time(ticks: int, domain: str = "cmap-output") -> dict:
    return {"ticks": ticks, "timebase": {"num": 1, "den": 1000}, "domain": domain}


def cue(asset: Path | None = None) -> dict:
    value = {
        "cueId": "cue-one",
        "start": time(100),
        "end": time(400),
        "kind": "text",
        "contentRef": {"text": "hello"},
        "targetLayerId": "graphics",
        "intent": "clarify",
        "reason": "spoken point",
        "reviewState": "pending",
    }
    if asset is not None:
        value["assetRef"] = {
            "locator": str(asset),
            "sha256": file_fingerprint(asset)["sha256"],
            "sizeBytes": asset.stat().st_size,
        }
    return value


def test_authors_replayable_bmap_on_exact_approved_cut(tmp_path: Path) -> None:
    workspace, cmap, cut_hash = approved_workspace(tmp_path)
    service = BMapService(workspace)
    first = service.author({"cues": [cue()]}, actor="avo", reason="beat one")
    assert first["snapshot"]["basis"]["revisionId"] == cmap["revisionId"]
    assert first["snapshot"]["basis"]["outputSha256"] == cut_hash
    assert first["diff"][0]["op"] == "add"
    changed = cue()
    changed["end"] = time(500)
    second = service.author({"cues": [changed]}, actor="avo", reason="extend")
    assert second["diff"][0]["op"] == "replace"


@pytest.mark.parametrize("mutation", ["raw-time", "outside", "asset-missing"])
def test_rejects_invalid_timing_and_assets(tmp_path: Path, mutation: str) -> None:
    workspace, _, _ = approved_workspace(tmp_path)
    value = cue()
    if mutation == "raw-time":
        value["start"] = {**time(100, "raw-source"), "sourceId": "camera"}
    elif mutation == "outside":
        value["end"] = time(2000)
    else:
        value["assetRef"] = {
            "locator": str(tmp_path / "missing.png"),
            "sha256": "a" * 64,
            "sizeBytes": 1,
        }
    with pytest.raises(LineageError):
        BMapService(workspace).author({"cues": [value]}, actor="avo", reason="invalid")


def test_newer_unapproved_cmap_head_blocks_bmap(tmp_path: Path) -> None:
    workspace, _, _ = approved_workspace(tmp_path)
    BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="beat")
    raw = workspace.raw_dir / "raw.bin"
    CMapService(workspace).author(
        snapshot(raw, start=50, end=950), actor="avo", reason="new head"
    )
    with pytest.raises(LineageError, match="latest effective"):
        BMapService(workspace).author({"cues": [cue()]}, actor="avo", reason="blocked")
