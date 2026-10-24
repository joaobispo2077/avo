"""Briefing authority survives reconstruction and metadata-only cleanup previews."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from avo import project_inventory
from avo.direction.brief import BriefService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.reconstruction import (
    ReconstructionError,
    build_reconstruction_bundle,
    verify_reconstruction_bundle,
)
from avo.timeline.workspace import TimelineWorkspace
from tests.test_briefstart_context import project_fixture, selected_project


def reconstruction_fixture(project: Path):
    """Tiny byte fixtures exercise retention; none is playable source media."""
    raw = project.parent
    (raw / "source.bin").write_bytes(b"synthetic raw input")
    workspace = TimelineWorkspace.from_project(project)
    workspace.initialize()
    for kind in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        workspace.store(kind).append_revision(
            snapshot={"kind": kind}, actor="agent", reason="neutral retention fixture"
        )
    basename = "neutral-master-v001"
    master = raw / "edit/masters" / f"{basename}.mp4"
    master.parent.mkdir(parents=True, exist_ok=True)
    master.write_bytes(b"synthetic delivery identity only")
    transcript = raw / "edit/transcripts" / f"{basename}.json"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        json.dumps(
            {"source": {"sha256": file_fingerprint(master)["sha256"]}, "words": []}
        ),
        encoding="utf-8",
    )
    transcript.with_suffix(".txt").write_text("Neutral fixture.\n", encoding="utf-8")
    (transcript.parent / "initial.json").write_text("{}", encoding="utf-8")
    return workspace, basename


def test_bundle_and_cleanup_preview_protect_selected_authority_and_history(tmp_path):
    project, service, _, _ = selected_project(tmp_path)
    service.stage_context("motion", record=True)
    root = project.parent / "edit/briefstart"
    protected = {path.resolve() for path in root.rglob("*") if path.is_file()}
    assert any(path.parent.name == "frozen" for path in protected)
    assert any(path.parent.name == "decisions" for path in protected)
    workspace, basename = reconstruction_fixture(project)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="neutral-test"
    )
    bundled = {(project.parent / entry["path"]).resolve() for entry in bundle["files"]}
    assert protected <= bundled
    before = {path: path.read_bytes() for path in protected}
    result = project_inventory.run_cleanup(project.parent, basename, dry_run=True)
    assert protected <= set(result.preserved.all_paths)
    assert not protected.intersection(result.paths)
    assert all(path.read_bytes() == encoded for path, encoded in before.items())


def test_replay_and_bundle_verification_need_no_original_provider_tree(tmp_path):
    project, _, brief_ref, _ = selected_project(tmp_path, provider_mode=True)
    workspace, basename = reconstruction_fixture(project)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="neutral-test"
    )
    shutil.rmtree(tmp_path / "neutral")
    assert (
        verify_reconstruction_bundle(project.parent)["bundleSha256"]
        == bundle["bundleSha256"]
    )
    context = BriefService(project, provider_root=tmp_path / "neutral").stage_context(
        "structure"
    )
    assert context["refs"]["brief"] == brief_ref


def test_descriptor_locator_never_adds_historical_media_to_reconstruction(
    tmp_path, monkeypatch
):
    from tests import test_briefstart_context

    outside = tmp_path / "historical-master.mp4"
    outside.write_bytes(b"historical reference must not be admitted as an ancestor")
    original = test_briefstart_context.reference
    monkeypatch.setattr(
        test_briefstart_context,
        "reference",
        lambda: {**original(), "locator": str(outside)},
    )
    project, _, _, _ = selected_project(tmp_path)
    workspace, basename = reconstruction_fixture(project)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="neutral-test"
    )
    assert all(
        (project.parent / entry["path"]).resolve() != outside.resolve()
        for entry in bundle["files"]
    )
    outside.unlink()
    verify_reconstruction_bundle(project.parent)


def test_changed_frozen_authority_invalidates_existing_bundle(tmp_path):
    project, _, _, _ = selected_project(tmp_path)
    workspace, basename = reconstruction_fixture(project)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="neutral-test"
    )
    frozen = next((project.parent / "edit/briefstart/frozen").glob("*.json"))
    assert frozen.relative_to(project.parent).as_posix() in {
        entry["path"] for entry in bundle["files"]
    }
    verify_reconstruction_bundle(project.parent)
    frozen.write_text("{}", encoding="utf-8")
    with pytest.raises(ReconstructionError):
        verify_reconstruction_bundle(project.parent)


def test_no_reference_reconstruction_needs_no_briefing_directory(tmp_path):
    project = project_fixture(tmp_path)
    workspace, basename = reconstruction_fixture(project)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="neutral-test"
    )
    verify_reconstruction_bundle(project.parent)
    assert not (project.parent / "edit/briefstart").exists()
    assert not any(
        entry["path"].startswith("edit/briefstart/") for entry in bundle["files"]
    )
    project_inventory.run_cleanup(project.parent, basename, dry_run=True)
    assert not (project.parent / "edit/briefstart").exists()
