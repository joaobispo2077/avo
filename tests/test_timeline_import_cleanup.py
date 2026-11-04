"""Cleanup preserves exact active import evidence and the shared writer lock."""

import json
from threading import Thread

import pytest

from avo import project_inventory
from avo.adapters.media.otio_reader import read_otio
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_retention import retained_import_paths
from avo.timeline.import_service import TimelineImportService
from avo.timeline.reconstruction import build_reconstruction_bundle
from avo.timeline.store import StoreError, timeline_writer
from tests.test_timeline_import_findings import _declarations
from tests.test_timeline_import_media import _mapping
from tests.test_timeline_import_service import (
    FIXTURE,
    REFERENCE,
    _approve_fixture_sync,
    _probe,
)
from tests.test_timeline_import_service import import_project as _project


def _cleanup_import(
    tmp_path, *, custom=False, alternate=False, external=False, active=True
):
    pytest.importorskip("opentimelineio")
    project, provider, original = _project.__wrapped__(tmp_path)
    document = json.loads(project.read_text())
    if custom:
        document["timeline"] = {"directory": "edit/canonical-custom"}
    if alternate:
        alternate_path = project.parent / "editing.project.json"
        project.unlink()
        project = alternate_path
    project.write_text(json.dumps(document))
    if external:
        outside = tmp_path / "external-originals" / original.name
        outside.parent.mkdir()
        outside.write_bytes(original.read_bytes())
        original.unlink()
        original = outside
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    options = {
        "media_roots": [original.parent],
        "mappings": {REFERENCE: _mapping(original)},
        "declarations": _declarations(),
        "actor": "fixture",
        "reason": "Synthetic cleanup handoff",
    }
    staged = service.prepare(FIXTURE, **options)
    if active:
        waiting = service.validate(staged["importId"])
        # Explicit fixture-only Sync evidence does not grant production approval.
        _approve_fixture_sync(service, waiting["proposal"])
        ready = service.validate(staged["importId"])
        service.activate(
            staged["importId"],
            validation_hash=ready["validationHash"],
            expected_head="empty",
            actor="fixture",
            reason="Select synthetic cleanup draft",
        )
    orphan_export = tmp_path / "unselected.otio"
    orphan_document = json.loads(FIXTURE.read_text())
    orphan_document["name"] = "Unselected staged import"
    orphan_export.write_text(json.dumps(orphan_document))
    orphan = service.prepare(orphan_export, **options)
    basename = "synthetic-cleanup-master-v001"
    raw = service.workspace.raw_dir
    master = raw / "edit" / "masters" / f"{basename}.mp4"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"synthetic final artifact, not native video fidelity")
    transcript = raw / "edit" / "transcripts" / f"{basename}.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {"source": {"sha256": file_fingerprint(master)["sha256"]}, "words": []}
        )
    )
    (transcript.parent / "initial.json").write_text("{}")
    return service, basename, orphan, original


@pytest.mark.parametrize(
    "custom,alternate", [(False, False), (True, False), (True, True)]
)
def test_cleanup_uses_declared_timeline_and_retains_only_referenced_import_packets(
    tmp_path, custom, alternate
):
    service, basename, orphan, _ = _cleanup_import(
        tmp_path, custom=custom, alternate=alternate
    )
    workspace = service.workspace
    required = set(retained_import_paths(workspace))
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="fixture"
    )
    assert required <= {workspace.raw_dir / row["path"] for row in bundle["files"]}
    outcome = project_inventory.run_cleanup(
        workspace.raw_dir,
        basename,
        dry_run=True,
        project_path=workspace.project_path,
        purge_session=False,
    )
    assert not required.intersection(outcome.paths)
    assert required <= set(outcome.preserved.all_paths)
    assert service.packet_path(orphan["importId"], "source.otio") in outcome.paths
    assert not any(path.name == ".mutation.lock" for path in outcome.paths)


def test_fallback_metadata_does_not_blanket_preserve_unselected_import_json(tmp_path):
    service, basename, orphan, _ = _cleanup_import(tmp_path)
    preserved = project_inventory.resolve_preserved_set(
        service.workspace.raw_dir, basename, project_path=service.workspace.project_path
    )
    assert set(retained_import_paths(service.workspace)) <= set(preserved.all_paths)
    assert service.packet_path(orphan["importId"]) not in preserved.all_paths
    assert (
        service.packet_path(orphan["importId"], "source.otio")
        not in preserved.all_paths
    )


def test_verified_external_originals_satisfy_source_requirement_without_local_copy(
    tmp_path,
):
    service, basename, _, original = _cleanup_import(tmp_path, external=True)
    workspace = service.workspace
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="fixture"
    )
    assert bundle["externalSources"]
    assert all(
        (workspace.raw_dir / row["path"]).resolve() != original.resolve()
        for row in bundle["files"]
    )
    outcome = project_inventory.run_cleanup(
        workspace.raw_dir,
        basename,
        dry_run=True,
        project_path=workspace.project_path,
        purge_session=False,
    )
    assert original not in outcome.paths
    assert all(
        path.resolve().is_relative_to(workspace.raw_dir)
        for path in outcome.preserved.all_paths
    )
    assert original.is_file()


def test_injected_kernel_lock_candidate_is_refused_before_deletion(tmp_path):
    lock = tmp_path / "edit" / "timeline" / ".mutation.lock"
    lock.parent.mkdir(parents=True)
    lock.write_bytes(b"kernel coordination")
    preserved = project_inventory.PreservedSetResult([], None, [], [])
    with pytest.raises(project_inventory.PreservedSetViolation, match="lock|preserved"):
        project_inventory.assert_no_preserved_in_delete_list(preserved, [lock])
    assert lock.read_bytes() == b"kernel coordination"


def test_cleanup_holds_actual_canonical_writer_through_verification_and_deletion(
    tmp_path,
):
    service, basename, _, _ = _cleanup_import(tmp_path, custom=True, alternate=True)
    workspace = service.workspace
    build_reconstruction_bundle(workspace, master_basename=basename, actor="fixture")
    disposable = workspace.raw_dir / "edit" / "cache" / "disposable.bin"
    disposable.parent.mkdir()
    disposable.write_bytes(b"disposable")
    lock = workspace.timeline_dir / ".mutation.lock"
    before = lock.stat()
    attempts = []

    def competing_writer():
        try:
            with timeline_writer(workspace.timeline_dir):
                attempts.append("entered")
        except StoreError:
            attempts.append("blocked")

    def remove(path):
        worker = Thread(target=competing_writer)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert attempts[-1] == "blocked"
        path.unlink()

    project_inventory.run_cleanup(
        workspace.raw_dir,
        basename,
        project_path=workspace.project_path,
        rimraf_runner=remove,
        purge_session=False,
    )
    assert attempts and set(attempts) == {"blocked"}
    assert not disposable.exists()
    after = lock.stat()
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


@pytest.mark.parametrize("damage", ["malformed", "different-raw"])
def test_explicit_invalid_cleanup_project_cannot_fall_back_to_other_authority(
    tmp_path, damage
):
    service, basename, _, _ = _cleanup_import(tmp_path)
    workspace = service.workspace
    invalid = tmp_path / "invalid.project.json"
    if damage == "malformed":
        invalid.write_text("{")
    else:
        other = tmp_path / "other-footage"
        other.mkdir()
        invalid.write_text(
            json.dumps(
                {"provider": "channel", "videoId": "other", "rawDir": str(other)}
            )
        )
    attempted = []
    head = service.head_hash()
    with pytest.raises((ValueError, RuntimeError)):
        project_inventory.run_cleanup(
            workspace.raw_dir,
            basename,
            project_path=invalid,
            rimraf_runner=attempted.append,
            purge_session=False,
        )
    assert attempted == []
    assert service.head_hash() == head


def test_alternate_project_preservation_closure_uses_its_actual_manifest_and_policy(
    tmp_path,
):
    service, basename, _, _ = _cleanup_import(tmp_path, custom=True, alternate=True)
    workspace = service.workspace
    project = json.loads(workspace.project_path.read_text())
    project["cleanup"] = {"preservePaths": ["edit"]}
    workspace.project_path.write_text(json.dumps(project))
    build_reconstruction_bundle(workspace, master_basename=basename, actor="fixture")
    _, receipt = project_inventory.record_preservation_closure(
        workspace.raw_dir, basename, project_path=workspace.project_path
    )
    assert receipt["project"]["locator"] == str(workspace.project_path.resolve())
    assert receipt["reconstructionBundle"]["locator"] == str(
        workspace.timeline_dir / "reconstruction-bundle.json"
    )
    _, checked = project_inventory.verify_preservation_closure(
        workspace.raw_dir, basename, project_path=workspace.project_path
    )
    assert checked["receiptSha256"] == receipt["receiptSha256"]


@pytest.mark.parametrize("damage", ["missing-tracks", "corrupt-tracks", "missing-cmap"])
def test_damaged_canonical_index_never_degrades_import_cleanup_to_legacy(
    tmp_path, damage
):
    service, basename, _, _ = _cleanup_import(tmp_path)
    workspace = service.workspace
    required = set(retained_import_paths(workspace))
    build_reconstruction_bundle(workspace, master_basename=basename, actor="fixture")
    target = workspace.artifact_path("cmap" if damage == "missing-cmap" else "tracks")
    if damage.startswith("missing"):
        target.unlink()
    else:
        target.write_text("{}")
    with pytest.raises(
        (SystemExit, project_inventory.PreservedSetViolation, RuntimeError, ValueError)
    ):
        project_inventory.run_cleanup(
            workspace.raw_dir,
            basename,
            dry_run=True,
            project_path=workspace.project_path,
            purge_session=False,
        )
    assert all(path.is_file() for path in required)


def test_lost_canonical_indexes_cannot_make_selected_import_history_disposable(
    tmp_path,
):
    service, basename, _, _ = _cleanup_import(tmp_path)
    workspace = service.workspace
    required = set(retained_import_paths(workspace))
    for name in project_inventory.CANONICAL_INDEX_NAMES:
        workspace.artifact_path(name).unlink()
    with pytest.raises(
        (SystemExit, project_inventory.PreservedSetViolation, RuntimeError, ValueError)
    ):
        project_inventory.run_cleanup(
            workspace.raw_dir,
            basename,
            dry_run=True,
            project_path=workspace.project_path,
            purge_session=False,
        )
    assert all(path.is_file() for path in required)


def test_provably_unselected_prepared_packets_remain_disposable_without_canonical_state(
    tmp_path,
):
    service, basename, orphan, _ = _cleanup_import(tmp_path, active=False)
    outcome = project_inventory.run_cleanup(
        service.workspace.raw_dir,
        basename,
        dry_run=True,
        project_path=service.workspace.project_path,
        purge_session=False,
    )
    assert service.packet_path(orphan["importId"], "source.otio") in outcome.paths
    assert service.packet_path(orphan["importId"]) in outcome.paths
    assert not service.workspace.artifact_path("cmap").exists()


def test_unknown_alternate_project_cannot_select_default_cleanup_authority(tmp_path):
    service, basename, _, _ = _cleanup_import(tmp_path, custom=True, alternate=True)
    workspace = service.workspace
    required = set(retained_import_paths(workspace))
    build_reconstruction_bundle(workspace, master_basename=basename, actor="fixture")
    with pytest.raises(
        (SystemExit, project_inventory.PreservedSetViolation, RuntimeError, ValueError)
    ):
        project_inventory.run_cleanup(
            workspace.raw_dir, basename, dry_run=True, purge_session=False
        )
    assert all(path.is_file() for path in required)


def test_unknown_canonical_metadata_arriving_during_scan_is_not_deleted(
    tmp_path, monkeypatch
):
    service, basename, _, _ = _cleanup_import(tmp_path, active=False)
    workspace = service.workspace
    # Remove only never-selected fixture packets, leaving a plain legacy tree.
    for packet in service.root.iterdir():
        for path in packet.iterdir():
            path.unlink()
        packet.rmdir()
    service.root.rmdir()
    workspace.project_path.unlink()
    real_scan = project_inventory.scan_delete_candidates
    arriving = workspace.raw_dir / "edit" / "incoming-canonical" / "cmap.json"

    def scan_after_arrival(raw_dir, preserved):
        arriving.parent.mkdir()
        arriving.write_text('{"artifactType":"cmap"}')
        return real_scan(raw_dir, preserved)

    monkeypatch.setattr(project_inventory, "scan_delete_candidates", scan_after_arrival)
    attempted = []
    with pytest.raises(project_inventory.PreservedSetViolation):
        project_inventory.run_cleanup(
            workspace.raw_dir,
            basename,
            rimraf_runner=attempted.append,
            purge_session=False,
        )
    assert attempted == []
    assert arriving.read_text() == '{"artifactType":"cmap"}'
