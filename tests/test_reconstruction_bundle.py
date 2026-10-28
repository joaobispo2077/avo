from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo import project_inventory
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.iterations import IterationLedgerService
from avo.timeline.reconstruction import (
    ReconstructionError,
    build_reconstruction_bundle,
    verify_reconstruction_bundle,
)
from avo.timeline.workspace import TimelineWorkspace


def canonical_project(tmp_path: Path, *, master_subdir: str = "masters"):
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
    master = tmp_path / "edit" / master_subdir / f"{basename}.mp4"
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


def test_wrap_sidecars_are_not_reconstruction_sources(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    sidecars = [
        tmp_path / "avo.wrap.json",
        tmp_path / "avo.wrap.md",
        tmp_path / "avo.wrap.draft.json",
    ]
    for path in sidecars:
        path.write_text("pending closure", encoding="utf-8")
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    assert not {path.name for path in sidecars} & {
        entry["path"] for entry in bundle["files"]
    }
    for path in sidecars:
        assert path.read_text(encoding="utf-8") == "pending closure"
        path.write_text("final closure", encoding="utf-8")
    assert (
        verify_reconstruction_bundle(tmp_path)["bundleSha256"] == bundle["bundleSha256"]
    )


def test_verifier_hashes_master_once_in_its_own_file_loop(tmp_path, monkeypatch):
    from avo.timeline import reconstruction

    workspace, basename = canonical_project(tmp_path)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    master = tmp_path / bundle["master"]["path"]
    original = reconstruction.file_fingerprint
    calls = []

    def counted(path):
        calls.append(Path(path).resolve())
        return original(path)

    monkeypatch.setattr(reconstruction, "file_fingerprint", counted)
    verify_reconstruction_bundle(tmp_path)
    assert calls.count(master.resolve()) == 1
    assert sorted(calls) == sorted(
        (tmp_path / entry["path"]).resolve() for entry in bundle["files"]
    )


def test_verification_rereads_changed_master_with_same_size_and_date(tmp_path):
    import os

    workspace, basename = canonical_project(tmp_path)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    master = tmp_path / bundle["master"]["path"]
    before = master.stat()
    master.write_bytes(b"MASTER-BYTES")
    os.utime(master, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert master.stat().st_size == before.st_size
    assert master.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(ReconstructionError, match="file changed"):
        verify_reconstruction_bundle(tmp_path)


def human_final_authority_files(workspace):
    raw_dir = workspace.raw_dir
    decision = raw_dir / "edit" / "cleanup" / "closure" / "decision.json"
    original = raw_dir / "edit" / "reference" / "original-acceptance.json"
    report = raw_dir / "edit" / "cleanup" / "closure" / "transcript-analysis.json"
    disposition = workspace.timeline_dir / "approvals" / "human-final-fixture.json"
    for path in (decision, original, report, disposition):
        path.parent.mkdir(parents=True, exist_ok=True)
    decision.write_text('{"decision":"approved"}', encoding="utf-8")
    original.write_text('{"type":"approved"}', encoding="utf-8")
    report.write_text('{"status":"fail"}', encoding="utf-8")

    def reference(path):
        return {"path": str(path), **file_fingerprint(path)}

    disposition.write_text(
        json.dumps(
            {
                "authority": "human-final",
                "decisionRef": reference(decision),
                "sourceApprovalRef": reference(original),
                "automatedEvidence": {
                    "transcript-analysis": {**reference(report), "status": "fail"}
                },
                "automatedOutcomesReclassified": False,
            }
        ),
        encoding="utf-8",
    )
    (raw_dir / "edit" / "delivery-manifest.json").write_text(
        json.dumps(
            {
                "state": "delivered",
                "adoption": {"humanFinalDisposition": reference(disposition)},
            }
        ),
        encoding="utf-8",
    )
    return [decision, original, report, disposition]


def test_human_final_authority_and_original_decision_are_required_inputs(tmp_path):
    workspace, basename = canonical_project(tmp_path)
    authority = human_final_authority_files(workspace)
    original = {path: path.read_bytes() for path in authority}
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    assert {path.relative_to(tmp_path).as_posix() for path in authority} <= {
        entry["path"] for entry in bundle["files"]
    }
    verify_reconstruction_bundle(tmp_path)
    assert all(path.read_bytes() == data for path, data in original.items())


@pytest.mark.parametrize("change", ["changed-decision", "omitted-decision"])
def test_human_final_authority_cannot_disappear_from_verified_bundle(tmp_path, change):
    workspace, basename = canonical_project(tmp_path)
    decision, *_ = human_final_authority_files(workspace)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    if change == "changed-decision":
        decision.write_text('{"decision":"rejected"}', encoding="utf-8")
    else:
        bundle["files"] = [
            entry
            for entry in bundle["files"]
            if entry["path"] != decision.relative_to(tmp_path).as_posix()
        ]
        bundle["bundleSha256"] = content_hash(
            {key: value for key, value in bundle.items() if key != "bundleSha256"}
        )
        (workspace.timeline_dir / "reconstruction-bundle.json").write_text(
            json.dumps(bundle), encoding="utf-8"
        )
    with pytest.raises(ReconstructionError):
        verify_reconstruction_bundle(tmp_path)


@pytest.mark.parametrize("change", ["missing-file-entry", "wrong-master-digest"])
def test_master_must_match_the_entry_verified_in_the_file_loop(tmp_path, change):
    workspace, basename = canonical_project(tmp_path)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    if change == "missing-file-entry":
        bundle["files"] = [
            entry
            for entry in bundle["files"]
            if entry["path"] != bundle["master"]["path"]
        ]
    else:
        bundle["master"]["sha256"] = "f" * 64
    bundle["bundleSha256"] = content_hash(
        {key: value for key, value in bundle.items() if key != "bundleSha256"}
    )
    (workspace.timeline_dir / "reconstruction-bundle.json").write_text(
        json.dumps(bundle), encoding="utf-8"
    )
    with pytest.raises(ReconstructionError, match="master"):
        verify_reconstruction_bundle(tmp_path)


@pytest.mark.parametrize("tampered", [False, True])
def test_explicit_export_location_keeps_exact_transcript_hash_gate(
    tmp_path: Path, tampered: bool
):
    workspace, basename = canonical_project(tmp_path, master_subdir="proofs")
    master = tmp_path / "edit" / "proofs" / f"{basename}.mp4"
    fingerprint = file_fingerprint(master)
    (tmp_path / "edit" / "delivery-manifest.json").write_text(
        json.dumps({"master": {**fingerprint, "path": str(master)}}),
        encoding="utf-8",
    )
    if tampered:
        master.write_bytes(b"MASTER-BYTES")
        with pytest.raises(ReconstructionError, match="exact master bytes"):
            build_reconstruction_bundle(
                workspace, master_basename=basename, actor="creator"
            )
        assert not (workspace.timeline_dir / "reconstruction-bundle.json").exists()
    else:
        bundle = build_reconstruction_bundle(
            workspace, master_basename=basename, actor="creator"
        )
        assert bundle["master"]["path"] == f"edit/proofs/{basename}.mp4"
        assert bundle["master"]["sha256"] == fingerprint["sha256"]
        assert verify_reconstruction_bundle(tmp_path)["master"] == bundle["master"]
        assert project_inventory.resolve_preserved_set(
            tmp_path, basename
        ).final_master == [master]


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


def historical_request_ledger(workspace: TimelineWorkspace) -> Path:
    request = workspace.review_dir / "historical-cut" / "request.json"
    request.parent.mkdir(parents=True)
    ledger = IterationLedgerService(workspace)
    for version in ("first request", "revised request"):
        request.write_text(version, encoding="utf-8")
        ledger.record_iteration(
            {
                "intent": {"request": file_fingerprint(request)},
                "canonicalBasis": {"cmap": workspace.store("cmap").head_hash()},
                "proofPlanRef": {"artifactId": "historical-plan", "sha256": "a" * 64},
            },
            actor="agent",
            reason="historical request fixture",
        )
    ledger.store.set_active_state(
        "valid", reason="fixture history event", actor="agent"
    )
    return request


def ledger_file_bytes(workspace: TimelineWorkspace) -> dict[str, bytes]:
    index_path = workspace.timeline_dir / "iteration-ledger.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    paths = [
        index_path,
        *[
            workspace.timeline_dir / ref["path"]
            for ref in [*index["revisionRefs"], *index["eventRefs"]]
        ],
    ]
    return {
        path.relative_to(workspace.raw_dir).as_posix(): path.read_bytes()
        for path in paths
    }


@pytest.mark.parametrize("request_exists", [True, False])
def test_historical_ledger_refs_are_not_current_media_requirements(
    tmp_path: Path, request_exists: bool
):
    workspace, basename = canonical_project(tmp_path)
    request = historical_request_ledger(workspace)
    if not request_exists:
        request.unlink()
    original_ledger = ledger_file_bytes(workspace)

    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    assert ledger_file_bytes(workspace) == original_ledger
    assert {entry["path"] for entry in bundle["iterationLedgers"]} == set(
        original_ledger
    )
    files = {entry["path"]: entry for entry in bundle["files"]}
    assert set(original_ledger) <= files.keys()
    request_relative = request.relative_to(tmp_path).as_posix()
    if request_exists:
        assert files[request_relative]["sha256"] == file_fingerprint(request)["sha256"]
    else:
        assert request_relative not in files
    assert (
        verify_reconstruction_bundle(tmp_path)["bundleSha256"] == bundle["bundleSha256"]
    )


@pytest.mark.parametrize("role", ["revision", "event"])
@pytest.mark.parametrize("change", ["changed", "missing"])
def test_ledger_archive_integrity_remains_required(
    tmp_path: Path, change: str, role: str
):
    workspace, basename = canonical_project(tmp_path)
    historical_request_ledger(workspace)
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    entry = next(
        item for item in bundle["iterationLedgers"] if item["role"].endswith(role)
    )
    path = tmp_path / entry["path"]
    if change == "changed":
        path.write_bytes(b"changed historical record")
    else:
        path.unlink()
    with pytest.raises(ReconstructionError):
        verify_reconstruction_bundle(tmp_path)


def test_conflicting_current_media_heads_still_block_bundle(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    media = tmp_path / "edit" / "current-input.bin"
    media.write_bytes(b"first selected input")
    workspace.store("tracks").append_revision(
        snapshot={"source": file_fingerprint(media)}, actor="agent", reason="fixture"
    )
    media.write_bytes(b"other selected input")
    workspace.store("animation").append_revision(
        snapshot={"source": file_fingerprint(media)}, actor="agent", reason="fixture"
    )
    with pytest.raises(ReconstructionError, match="conflicting canonical media"):
        build_reconstruction_bundle(
            workspace, master_basename=basename, actor="creator"
        )


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


@pytest.mark.parametrize(
    "artifact_type", ["cmap", "bmap", "tracks", "animation", "sync-map"]
)
def test_missing_or_changed_canonical_media_blocks_bundle(
    tmp_path: Path, artifact_type: str
):
    workspace, basename = canonical_project(tmp_path)
    media = tmp_path / "edit" / "dialogue.wav"
    media.write_bytes(b"dialogue")
    workspace.store(artifact_type).append_revision(
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


# Synthetic metadata/media fixture for retention only; this is not render evidence.
def code_drawn_retention_fixture(tmp_path: Path):
    from avo.adapters.motion.code_drawn import CodeDrawnAdapter
    from avo.motion import (
        freeze_code_drawn_lock,
        load_composition,
        scaffold_code_drawn,
        seal_composition,
    )
    from avo.timeline.store import write_immutable_json
    from tests.test_timeline_animation_service import strategy

    workspace, basename = canonical_project(tmp_path)
    instance = "retained-title"
    root = workspace.raw_dir / "edit" / "derived" / "components" / instance
    scaffold_code_drawn(
        root,
        route="canvas",
        width=128,
        height=96,
        fps="30/1",
        frames=12,
        background="transparent",
    )
    manifest_path = root / "composition.json"
    manifest = load_composition(manifest_path)
    manifest["compositionId"] = instance
    assets = {
        "assets/type.woff2": (b"synthetic font dependency", "font", "font-fixture"),
        "assets/logo.svg": (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>',
            "svg",
            "svg-fixture",
        ),
        "assets/image.png": (b"synthetic image dependency", "image", "image-fixture"),
        "assets/LICENSE.md": (
            b"Self-authored synthetic test dependency",
            "data",
            "license-fixture",
        ),
    }
    for relative, (data, kind, asset_id) in assets.items():
        target = root / relative
        target.write_bytes(data)
        fields = (
            {"family": "FixtureFace", "style": "normal", "weight": 400}
            if kind == "font"
            else {}
        )
        manifest["assets"].append(
            {
                "id": asset_id,
                "kind": kind,
                "path": relative,
                "sha256": file_fingerprint(target)["sha256"],
                "sizeBytes": len(data),
                "rightsRef": "ANIMATION-SOURCE-LOG.md",
                **fields,
            }
        )
    brush = root / "assets" / "brush.js"
    brush.write_bytes(
        b"// Synthetic brush dependency; never executed in this unit fixture.\n"
    )
    manifest["dependencies"].append(
        {
            "name": "fixture-brush",
            "version": "1.0.0",
            "build": "unit-fixture",
            "path": "assets/brush.js",
            "sha256": file_fingerprint(brush)["sha256"],
            "sizeBytes": brush.stat().st_size,
            "licenseRef": "assets/LICENSE.md",
        }
    )
    manifest_path.write_text(json.dumps(seal_composition(manifest)), encoding="utf-8")
    manifest = load_composition(manifest_path)
    environment = {
        "platform": "unit-fixture",
        "dependencies": {"fixture": "1"},
        "browserVersion": "unit",
        "browserRevision": "unit",
        "graphics": "unit",
        "driverSha256": "a" * 64,
        "encoderSha256": "b" * 64,
        "locale": "en-US",
        "timezone": "UTC",
        "colorSpace": "srgb",
    }
    lock = freeze_code_drawn_lock(manifest_path, environment=environment)
    generated = workspace.raw_dir / "edit" / "derived" / "generated-media" / instance
    generated.mkdir(parents=True)
    lock_path = generated / "input-lock.json"
    write_immutable_json(lock_path, lock)
    output = generated / "asset.mkv"
    output.write_bytes(b"synthetic generated-media fixture, not a physical render")
    evidence = {
        "frames": list(range(10)),
        "rgbaSha256": ["c" * 64] * 10,
        "passes": ["repeat", "reverse", "fresh-session"],
        "environment": environment,
    }
    verification = {
        "width": 128,
        "height": 96,
        "frameRate": {"num": 30, "den": 1},
        "frameCount": 12,
        "silent": True,
        "codec": "ffv1",
        "pixelFormat": "bgra",
        "alphaMode": "straight",
        "rgbaRoundTrip": "exact",
        "colorRange": "full",
        "captureColorSpace": "srgb",
        "compositeColorSpace": "sdr-bt709",
        "controlledCompositeChecks": [],
    }
    record = CodeDrawnAdapter()._receipt(
        manifest_path, manifest, lock_path, lock, output, evidence, verification
    )
    record_path = (
        workspace.timeline_dir / "generated-assets" / (record["assetId"] + ".json")
    )
    write_immutable_json(record_path, record)
    value = strategy()
    value["framework"] = "code-drawn"
    component = value["components"][0]
    component.pop("providerPatternRef", None)
    component["componentId"] = instance
    component["extensions"] = {
        "codeDrawn": {
            "instanceId": instance,
            "manifestRef": {
                "path": manifest_path.relative_to(workspace.raw_dir).as_posix(),
                "sha256": file_fingerprint(manifest_path)["sha256"],
            },
        }
    }
    value["dependencies"] = {
        kind: workspace.store(kind).revision(
            workspace.store(kind).load_index()["headRevisionId"]
        )["contentHash"]
        for kind in ("cmap", "bmap", "tracks")
    }
    workspace.store("animation").append_revision(
        snapshot=value, actor="test-fixture", reason="Retain editable source"
    )
    return workspace, basename, manifest_path, lock_path, record_path, output


def test_code_drawn_bundle_preserves_referenced_lock_and_nontext_source_closure(
    tmp_path,
):
    workspace, basename, manifest, lock, record, output = code_drawn_retention_fixture(
        tmp_path
    )
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="test-reviewer"
    )
    included = {entry["path"] for entry in bundle["files"]}
    expected = {
        path.relative_to(workspace.raw_dir).as_posix()
        for path in (
            manifest,
            lock,
            record,
            manifest.parent / "index.html",
            manifest.parent / "assets/type.woff2",
            manifest.parent / "assets/logo.svg",
            manifest.parent / "assets/image.png",
            manifest.parent / "assets/brush.js",
            manifest.parent / "assets/LICENSE.md",
        )
    }
    assert expected <= included
    assert output.relative_to(workspace.raw_dir).as_posix() not in included


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_code_drawn_incomplete_or_changed_dependency_blocks_reconstruction(
    tmp_path, change
):
    workspace, basename, manifest, _lock, _record, _output = (
        code_drawn_retention_fixture(tmp_path)
    )
    font = manifest.parent / "assets/type.woff2"
    if change == "missing":
        font.unlink()
    else:
        font.write_bytes(b"different source, despite an unchanged manifest/receipt")
    with pytest.raises(
        ReconstructionError, match="type.woff2|drawing|dependency|fingerprint"
    ):
        build_reconstruction_bundle(
            workspace, master_basename=basename, actor="test-reviewer"
        )
    assert (workspace.raw_dir / "raw.bin").read_bytes() == b"raw-original"


def test_code_drawn_bundle_verification_rechecks_referenced_lock_coverage(tmp_path):
    from avo.timeline.contracts import document_hash_excluding

    workspace, basename, _manifest, lock, _record, _output = (
        code_drawn_retention_fixture(tmp_path)
    )
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="test-reviewer"
    )
    relative = lock.relative_to(workspace.raw_dir).as_posix()
    bundle["files"] = [entry for entry in bundle["files"] if entry["path"] != relative]
    bundle["bundleSha256"] = document_hash_excluding(bundle, "bundleSha256")
    (workspace.timeline_dir / "reconstruction-bundle.json").write_text(
        json.dumps(bundle), encoding="utf-8"
    )
    with pytest.raises(ReconstructionError, match="coverage|lock|dependency"):
        verify_reconstruction_bundle(workspace.raw_dir)
