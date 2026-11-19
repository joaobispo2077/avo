"""Applicable planning boundaries always expose pure, linked motion review."""

from __future__ import annotations

import builtins
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from avo.timeline.iterations import IterationLedgerService
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.store import ArtifactStore
from avo.timeline.workspace import TimelineWorkspace

BOUNDARIES = ("status", "briefing_status", "authoring_context")


@pytest.fixture
def workspace(tmp_path):
    """Use an external temporary project with every optional treatment disabled."""
    raw = tmp_path / "motion-defaults"
    raw.mkdir()
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "provider": "example",
                "videoId": "motion-defaults",
                "rawDir": str(raw),
                "editingCraft": {
                    "camera": {
                        "enabled": False,
                        "faceAnchor": "off",
                        "baseTreatment": "none",
                    },
                    "soundMatching": {
                        "enabled": False,
                        "mode": "descriptor",
                        "allowLayering": False,
                    },
                    "referenceAnalysis": {"enabled": False},
                    "spokenNotes": {"enabled": False},
                    "speechRecovery": {"enabled": False},
                    "handoff": {"mode": "none"},
                },
            }
        ),
        encoding="utf-8",
    )
    return TimelineWorkspace.from_project(project)


def _inspect(workspace, boundary):
    pipeline = TimelinePipeline(workspace)
    method = getattr(pipeline, boundary)
    return method("motion") if boundary == "authoring_context" else method()


def _tree(root):
    return {
        str(path.relative_to(root)): (
            path.stat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None,
        )
        for path in [root, *root.rglob("*")]
    }


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_default_boundary_exposes_linked_plan_before_any_timeline_exists(
    workspace, boundary
):
    before = _tree(workspace.raw_dir)
    result = _inspect(workspace, boundary)
    plan = result["motionPlan"]
    assert plan["applicability"] == "applicable"
    assert plan["readiness"] == "conceptual"
    assert plan["basisHeads"] == dict.fromkeys(
        ("cmap", "bmap", "tracks", "animation", "sync-map")
    )
    assert plan["items"] == plan["storyboardCards"] == []
    assert plan["lanes"] == {"audio": [], "video": []}
    assert "enableMotionMap" not in workspace.project["editingCraft"]
    assert _tree(workspace.raw_dir) == before


def _selected_context(variant):
    if variant == "skipped":
        return {"applicability": "explicitly-skipped"}
    item = {
        "itemId": "mo04",
        "label": "mo04",
        "sectionId": "opening",
        "concept": "Hold presenter while explaining",
        "purpose": "Clarify the idea",
        "treatment": "static",
    }
    if variant == "unresolved":
        item["assets"] = [{"kind": "logo", "status": "missing", "supplier": "creator"}]
    return {"proposal": {"items": [item]}}


@pytest.mark.parametrize("boundary", BOUNDARIES)
@pytest.mark.parametrize("variant", ["static", "unresolved", "skipped"])
def test_pipeline_keeps_selected_projection_without_enabling_treatments(
    workspace, monkeypatch, boundary, variant
):
    """Use real projection, inject only its selected metadata boundary.

    Proposal selection persistence is US1. This contract proves that each pipeline
    entrypoint exposes the service's actual partial/static/skipped result rather
    than suppressing it until a creative treatment is enabled.
    """
    from avo.timeline.motion_review import MotionReviewService

    expected = MotionReviewService(workspace).project(_selected_context(variant))
    calls = []

    def project_selected(service, context=None):
        assert service.workspace.project_path == workspace.project_path
        calls.append(context)
        return deepcopy(expected)

    monkeypatch.setattr(MotionReviewService, "project", project_selected)
    result = _inspect(workspace, boundary)
    assert calls
    assert result["motionPlan"] == expected
    if variant == "skipped":
        assert expected["applicability"] == "explicitly-skipped"
    else:
        assert expected["applicability"] == "applicable"
        assert (
            expected["items"][0]["itemId"]
            == expected["storyboardCards"][0]["itemId"]
            == "mo04"
        )
        assert expected["items"][0]["timingState"] == "provisional"
        if variant == "unresolved":
            assert expected["items"][0]["assetReadiness"] == "missing"


def _forbid_execution(monkeypatch, media):
    original_open, original_import = Path.open, builtins.__import__

    def forbidden(*args, **kwargs):
        raise AssertionError("Default motion inspection started execution or a write")

    def read_only_open(path, mode="r", *args, **kwargs):
        if any(character in mode for character in "wax+") or path.resolve() == media:
            forbidden()
        return original_open(path, mode, *args, **kwargs)

    def without_optional_models(name, *args, **kwargs):
        if name.split(".")[0] in {"cv2", "torch", "transformers", "onnxruntime"}:
            forbidden()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(Path, "open", read_only_open)
    for method in (
        "mkdir",
        "touch",
        "write_text",
        "write_bytes",
        "rename",
        "replace",
        "unlink",
    ):
        monkeypatch.setattr(Path, method, forbidden)
    monkeypatch.setattr(ArtifactStore, "initialize", forbidden)
    monkeypatch.setattr(IterationLedgerService, "__init__", forbidden)
    monkeypatch.setattr(TimelineWorkspace, "initialize", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(builtins, "__import__", without_optional_models)
    monkeypatch.setattr("avo.model_sources.preflight", forbidden)


@pytest.mark.parametrize("boundary", BOUNDARIES)
@pytest.mark.parametrize("initialized", [False, True])
def test_default_inspection_never_creates_state_or_reads_source_media(
    workspace, monkeypatch, boundary, initialized
):
    if initialized:
        workspace.initialize()
    media = workspace.raw_dir / "source.mp4"
    media.write_bytes(b"Raw source is intentionally not decoded by metadata inspection")
    before = _tree(workspace.raw_dir)
    with monkeypatch.context() as guard:
        _forbid_execution(guard, media.resolve())
        result = _inspect(workspace, boundary)
        assert result["motionPlan"]["applicability"] == "applicable"
    assert _tree(workspace.raw_dir) == before
    assert not (workspace.timeline_dir / "iteration-ledger.json").exists()


def test_all_default_boundaries_share_current_identity_without_publishing(workspace):
    plans = [_inspect(workspace, boundary)["motionPlan"] for boundary in BOUNDARIES]
    assert len({plan["snapshotHash"] for plan in plans}) == 1
    assert not (workspace.review_dir / "motion-plan").exists()
