from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo import project_inventory
from avo.timeline.contracts import file_fingerprint
from avo.timeline.reconstruction import (
    ReconstructionError,
    build_reconstruction_bundle,
    verify_reconstruction_bundle,
)
from avo.timeline.workspace import TimelineWorkspace


def canonical_project(tmp_path: Path):
    raw = tmp_path / "raw.bin"
    raw.write_bytes(b"raw-original")
    project = tmp_path / "avo.project.json"
    project.write_text(json.dumps({
        "schemaVersion": "1.0.0",
        "provider": "bishop",
        "videoId": "reconstruct",
        "rawDir": str(tmp_path),
    }), encoding="utf-8")
    workspace = TimelineWorkspace.from_project(project)
    workspace.initialize()
    for kind in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        workspace.store(kind).append_revision(
            snapshot={"kind": kind}, actor="agent", reason="fixture",
        )
    basename = "reconstruct-master-v001"
    master = tmp_path / "edit" / "masters" / f"{basename}.mp4"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"master-bytes")
    transcript = tmp_path / "edit" / "transcripts" / f"{basename}.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({
        "source": {"sha256": file_fingerprint(master)["sha256"]},
        "words": [],
    }), encoding="utf-8")
    (transcript.with_suffix(".txt")).write_text("text\n", encoding="utf-8")
    initial = transcript.parent / "initial.json"
    initial.write_text("{}", encoding="utf-8")
    return workspace, basename


def test_bundle_verifies_graph_and_cleanup_preserves_only_graph(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator",
    )
    assert len(bundle["canonicalArtifacts"]) == 5
    assert verify_reconstruction_bundle(tmp_path)["bundleSha256"] == bundle["bundleSha256"]
    scratch = tmp_path / "edit" / "preview" / "proof.mp4"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(b"bulky-proof")
    deleted = project_inventory.execute_cleanup(
        tmp_path, basename, dry_run=True,
    )
    assert scratch in deleted
    preserved = project_inventory.resolve_preserved_set(tmp_path, basename)
    assert workspace.artifact_path("cmap") in preserved.reconstruction_metadata


def test_cleanup_refuses_missing_or_changed_reconstruction_bundle(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    with pytest.raises(SystemExit, match="reconstruction"):
        project_inventory.execute_cleanup(tmp_path, basename, dry_run=True)
    build_reconstruction_bundle(workspace, master_basename=basename, actor="creator")
    workspace.artifact_path("cmap").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ReconstructionError):
        verify_reconstruction_bundle(tmp_path)
    with pytest.raises(SystemExit, match="reconstruction"):
        project_inventory.execute_cleanup(tmp_path, basename, dry_run=True)
