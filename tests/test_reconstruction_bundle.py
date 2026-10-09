from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo import project_inventory
from avo.timeline.contracts import content_hash, file_fingerprint
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
    project.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "bishop",
                "videoId": "reconstruct",
                "rawDir": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    workspace = TimelineWorkspace.from_project(project)
    workspace.initialize()
    for kind in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        workspace.store(kind).append_revision(
            snapshot={"kind": kind},
            actor="agent",
            reason="fixture",
        )
    basename = "reconstruct-master-v001"
    master = tmp_path / "edit" / "masters" / f"{basename}.mp4"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"master-bytes")
    transcript = tmp_path / "edit" / "transcripts" / f"{basename}.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {
                "source": {"sha256": file_fingerprint(master)["sha256"]},
                "words": [],
            }
        ),
        encoding="utf-8",
    )
    (transcript.with_suffix(".txt")).write_text("text\n", encoding="utf-8")
    initial = transcript.parent / "initial.json"
    initial.write_text("{}", encoding="utf-8")
    return workspace, basename


def test_bundle_verifies_graph_and_cleanup_preserves_only_graph(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    bundle = build_reconstruction_bundle(
        workspace,
        master_basename=basename,
        actor="creator",
    )
    assert len(bundle["canonicalArtifacts"]) == 5
    assert (
        verify_reconstruction_bundle(tmp_path)["bundleSha256"] == bundle["bundleSha256"]
    )
    scratch = tmp_path / "edit" / "preview" / "proof.mp4"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(b"bulky-proof")
    deleted = project_inventory.execute_cleanup(
        tmp_path,
        basename,
        dry_run=True,
    )
    assert scratch in deleted
    preserved = project_inventory.resolve_preserved_set(tmp_path, basename)
    assert workspace.artifact_path("cmap") in preserved.reconstruction_metadata


def test_bundle_and_cleanup_keep_shorts_delivery(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    shorts_root = tmp_path / "edit" / "shorts"
    batch = shorts_root / "campaign" / "demo-batch"
    (batch / "delivery" / "masters").mkdir(parents=True)
    (batch / "approvals").mkdir(parents=True)
    (batch / "work" / "01" / "proof-v001").mkdir(parents=True)
    index = shorts_root / "shorts.index.json"
    index.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "batches": [
                    {
                        "batchId": "demo-batch",
                        "batchRoot": str(batch),
                        "batchRootSource": "invocation",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    request = batch / "shorts.request-v001.json"
    request.write_text("{}\n", encoding="utf-8")
    status = batch / "plans" / "shorts.status.json"
    status.parent.mkdir(parents=True)
    status.write_text("{}\n", encoding="utf-8")
    approval = batch / "approvals" / "approval-v001.json"
    approval.write_text("{}\n", encoding="utf-8")
    master = batch / "delivery" / "masters" / "demo-short-01-master-v001.mp4"
    master.write_bytes(b"shorts-master")
    (batch / "plans" / "shorts.plan-v001.json").write_text("{}\n", encoding="utf-8")
    proof = batch / "work" / "01" / "proof-v001" / "out.mp4"
    proof.write_bytes(b"shorts-proof")
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    bundled = {tmp_path / item["path"] for item in bundle["files"]}
    assert {index, request, status, approval, master} <= bundled
    assert proof not in bundled
    assert all(
        item["role"] == "shorts-preservation"
        for item in bundle["files"]
        if (tmp_path / item["path"]) in {index, request, status, approval, master}
    )
    deleted = project_inventory.execute_cleanup(tmp_path, basename, dry_run=True)
    assert proof in deleted
    assert not ({index, request, status, approval, master} & set(deleted))


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


def test_reconstruction_preserves_fingerprinted_raw_review_artifacts(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    review_dir = workspace.review_dir / "cut-proof" / "candidate" / "watch"
    raw = review_dir / "raw" / "attempt-01.stdout.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("provider response", encoding="utf-8")
    review = review_dir.parent / "review.json"
    review.write_text(
        json.dumps(
            {
                "evidence": [
                    {
                        "kind": "watch",
                        "artifacts": [
                            {
                                "path": str(raw),
                                "sha256": file_fingerprint(raw)["sha256"],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    entry = next(item for item in bundle["files"] if item["path"].endswith(raw.name))
    assert entry["role"] == "review-raw-artifact"
    assert entry["sha256"] == file_fingerprint(raw)["sha256"]


def test_bundle_preserves_current_media_and_delivery_receipt(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    media = tmp_path / "edit" / "custom-audio" / "dialogue.wav"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"approved-dialogue")
    workspace.store("tracks").append_revision(
        snapshot={
            "layers": [{"source": {"locator": str(media), **file_fingerprint(media)}}]
        },
        actor="agent",
        reason="dialogue",
    )
    approval = tmp_path / "edit" / "delivery" / "v001" / "APPROVAL.json"
    approval.parent.mkdir(parents=True)
    approval.write_text("{}\n", encoding="utf-8")
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    bundled = {tmp_path / item["path"] for item in bundle["files"]}
    assert {media, approval} <= bundled
    assert not (
        {media, approval}
        & set(project_inventory.execute_cleanup(tmp_path, basename, dry_run=True))
    )

    # Even a correctly re-signed old/incomplete bundle must not permit deletion.
    bundle["files"] = [
        item for item in bundle["files"] if tmp_path / item["path"] != media
    ]
    bundle["bundleSha256"] = content_hash(
        {key: value for key, value in bundle.items() if key != "bundleSha256"}
    )
    (workspace.timeline_dir / "reconstruction-bundle.json").write_text(
        json.dumps(bundle), encoding="utf-8"
    )
    with pytest.raises(ReconstructionError, match="coverage"):
        verify_reconstruction_bundle(tmp_path)


def test_cleanup_respects_project_retention_and_actual_deletions(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    keep = tmp_path / "edit" / "preview" / "approved.mp4"
    discard = tmp_path / "edit" / "cache" / "unused.bin"
    for path in (keep, discard):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"media")
    project = json.loads(workspace.project_path.read_text(encoding="utf-8"))
    project["cleanup"] = {"preservePaths": ["edit/preview"]}
    workspace.project_path.write_text(json.dumps(project), encoding="utf-8")
    build_reconstruction_bundle(workspace, master_basename=basename, actor="creator")
    outcome = project_inventory.run_cleanup(
        tmp_path, basename, rimraf_runner=lambda path: None
    )
    assert keep.exists() and discard.exists()
    assert outcome.paths == []
    assert outcome.freed_bytes == 0
    assert outcome.leftover == 1
    receipt = json.loads(
        (tmp_path / "edit" / "cleanup" / "cleanup-result.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["deleted"] == []
    assert receipt["status"] == "incomplete"


@pytest.mark.parametrize("path", ["../outside", "/outside", "C:\\outside", "."])
def test_cleanup_rejects_unsafe_retention_paths(tmp_path: Path, path: str):
    workspace, basename = canonical_project(tmp_path)
    project = json.loads(workspace.project_path.read_text(encoding="utf-8"))
    project["cleanup"] = {"preservePaths": [path]}
    workspace.project_path.write_text(json.dumps(project), encoding="utf-8")
    with pytest.raises(project_inventory.PreservedSetViolation, match="preserve"):
        project_inventory.resolve_preserved_set(tmp_path, basename)


def test_final_wrap_requires_actual_cleanup_not_simulation(tmp_path: Path):
    from avo.wrap import build_wrap_payload

    workspace, basename = canonical_project(tmp_path)
    build_reconstruction_bundle(workspace, master_basename=basename, actor="creator")
    inventory = project_inventory.build_inventory_report(tmp_path, basename)
    with pytest.raises(ValueError, match="cleanup receipt"):
        build_wrap_payload(
            inventory,
            session_id="test",
            provider="bishop",
            master_basename=basename,
            summary="Done",
            status="final",
            freed_bytes=0,
        )
    outcome = project_inventory.run_cleanup(tmp_path, basename)
    assert outcome.freed_bytes == 0
    # A later, still-existing candidate must never become a claimed deletion.
    later = tmp_path / "edit" / "later.bin"
    later.write_bytes(b"not deleted")
    inventory = project_inventory.build_inventory_report(tmp_path, basename)
    final = build_wrap_payload(
        inventory,
        session_id="test",
        provider="bishop",
        master_basename=basename,
        summary="Done",
        status="final",
    )
    assert final["files"]["deletedCount"] == 0
    assert final["files"]["deletedOnCleanup"] == []
    assert final["space"]["freedBytes"] == 0


def test_successful_cleanup_receipt_drives_final_metrics(tmp_path: Path):
    from avo.wrap import build_wrap_payload

    workspace, basename = canonical_project(tmp_path)
    build_reconstruction_bundle(workspace, master_basename=basename, actor="creator")
    scratch = tmp_path / "edit" / "cache.bin"
    scratch.write_bytes(b"discard")
    outcome = project_inventory.run_cleanup(tmp_path, basename)
    assert outcome.paths == [scratch]
    assert outcome.freed_bytes == 7
    inventory = project_inventory.build_inventory_report(tmp_path, basename)
    final = build_wrap_payload(
        inventory,
        session_id="test",
        provider="bishop",
        master_basename=basename,
        summary="Done",
        status="final",
    )
    assert final["files"]["deletedCount"] == 1
    assert final["space"]["freedBytes"] == 7
    assert final["space"]["preCleanupProjectBytes"] == outcome.pre_cleanup_project_bytes
    assert final["files"]["deletedOnCleanup"] == [
        {"path": "edit/cache.bin", "bytes": 7}
    ]
    with pytest.raises(ValueError, match="override"):
        build_wrap_payload(
            inventory,
            session_id="test",
            provider="bishop",
            master_basename=basename,
            summary="Done",
            status="final",
            freed_bytes=0,
        )
    # A receipt cannot silently be replaced by a second execution.
    with pytest.raises(project_inventory.PreservedSetViolation, match="already exists"):
        project_inventory.run_cleanup(tmp_path, basename)


def test_missing_or_changed_canonical_media_blocks_bundle(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    media = tmp_path / "edit" / "dialogue.wav"
    media.write_bytes(b"dialogue")
    workspace.store("tracks").append_revision(
        snapshot={"source": file_fingerprint(media)}, actor="agent", reason="fixture"
    )
    media.write_bytes(b"changed")
    with pytest.raises(ReconstructionError, match="fingerprint changed"):
        build_reconstruction_bundle(
            workspace, master_basename=basename, actor="creator"
        )
    media.unlink()
    with pytest.raises(ReconstructionError, match="missing"):
        build_reconstruction_bundle(
            workspace, master_basename=basename, actor="creator"
        )
