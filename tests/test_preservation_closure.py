from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from avo import project_inventory, wrap
from avo.timeline.contracts import content_hash
from avo.timeline.reconstruction import build_reconstruction_bundle
from test_reconstruction_bundle import canonical_project


@pytest.fixture
def preservation_project(tmp_path: Path):
    workspace, basename = canonical_project(tmp_path)
    project = json.loads(workspace.project_path.read_text(encoding="utf-8"))
    project["cleanup"] = {"preservePaths": ["edit"]}
    workspace.project_path.write_text(json.dumps(project), encoding="utf-8")
    transcript = tmp_path / "edit" / "transcripts" / f"{basename}.json"
    for suffix in (".md", ".srt"):
        transcript.with_suffix(suffix).write_text("transcript", encoding="utf-8")
    proof = tmp_path / "edit" / "proofs" / "approved.mp4"
    proof.parent.mkdir()
    proof.write_bytes(b"approved proof")
    build_reconstruction_bundle(workspace, master_basename=basename, actor="creator")
    return workspace, basename, proof


def test_preservation_final_wrap_is_distinct_and_non_destructive(
    preservation_project, monkeypatch: pytest.MonkeyPatch
):
    workspace, basename, proof = preservation_project
    raw_dir = workspace.raw_dir
    before = {path: path.read_bytes() for path in raw_dir.rglob("*") if path.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("preservation closure must never execute cleanup or copy media")

    monkeypatch.setattr(project_inventory, "_recorded_deletes", forbidden)
    monkeypatch.setattr(project_inventory.shutil, "copy2", forbidden)
    json_path, md_path = wrap.finalize_preservation_wrap(
        raw_dir,
        master_basename=basename,
        session_id="preservation",
        provider="bishop",
        summary="Preserved without cleanup.",
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "final"
    assert payload["closure"]["mode"] == "preservation"
    assert payload["closure"]["cleanupExecuted"] is False
    assert payload["space"]["freedBytes"] is None
    assert payload["files"]["deletedCount"] == 0
    assert payload["files"]["deletedOnCleanup"] == []
    assert "not executed" in md_path.read_text(encoding="utf-8")
    assert not (raw_dir / "edit" / "cleanup" / "cleanup-result.json").exists()
    assert all(path.read_bytes() == data for path, data in before.items())
    assert proof.is_file()
    report, receipt = project_inventory.verify_preservation_closure(raw_dir, basename)
    assert report.delete_candidates == []
    assert receipt["candidateCount"] == receipt["leftoverCandidates"] == 0
    assert receipt["master"]["sha256"] == payload["closure"]["masterSha256"]


def test_one_pass_finalization_runs_native_byte_verification_once(
    preservation_project, monkeypatch: pytest.MonkeyPatch
):
    from avo.timeline import reconstruction

    workspace, basename, _ = preservation_project
    verify = reconstruction.verify_reconstruction_bundle
    calls = []

    def counted(*args, **kwargs):
        calls.append(args)
        return verify(*args, **kwargs)

    monkeypatch.setattr(reconstruction, "verify_reconstruction_bundle", counted)
    wrap.finalize_preservation_wrap(
        workspace.raw_dir,
        master_basename=basename,
        session_id="one-pass",
        provider="bishop",
        summary="Done.",
    )
    assert len(calls) == 1


def test_preservation_receipt_never_satisfies_default_cleanup_mode(
    preservation_project,
):
    workspace, basename, _ = preservation_project
    report, _ = project_inventory.record_preservation_closure(
        workspace.raw_dir, basename
    )
    with pytest.raises(ValueError, match="cleanup receipt"):
        wrap.build_wrap_payload(
            report,
            session_id="no-pretend-cleanup",
            provider="bishop",
            master_basename=basename,
            summary="Done.",
            status="final",
        )


@pytest.mark.parametrize("retention", [[], ["edit/proofs"], ["../outside"]])
def test_preservation_requires_explicit_retention_of_entire_deletion_scope(
    preservation_project, retention
):
    workspace, basename, _ = preservation_project
    project = json.loads(workspace.project_path.read_text(encoding="utf-8"))
    project["cleanup"]["preservePaths"] = retention
    workspace.project_path.write_text(json.dumps(project), encoding="utf-8")
    with pytest.raises(project_inventory.PreservedSetViolation, match="preserv"):
        project_inventory.record_preservation_closure(workspace.raw_dir, basename)


@pytest.mark.parametrize("leftover", [0, 1])
def test_preservation_refuses_candidates_or_scan_errors(
    preservation_project, monkeypatch: pytest.MonkeyPatch, leftover: int
):
    workspace, basename, proof = preservation_project
    monkeypatch.setattr(
        project_inventory,
        "scan_delete_candidates",
        lambda *args: ([proof] if not leftover else [], leftover),
    )
    with pytest.raises(project_inventory.PreservedSetViolation, match="candidate"):
        project_inventory.record_preservation_closure(workspace.raw_dir, basename)


@pytest.mark.parametrize(
    "tamper", ["receipt", "count", "master", "bundle", "added", "removed"]
)
def test_preservation_receipt_rejects_tampering_and_stale_scope(
    preservation_project, tamper: str
):
    workspace, basename, proof = preservation_project
    raw_dir = workspace.raw_dir
    project_inventory.record_preservation_closure(raw_dir, basename)
    receipt_path = raw_dir / "edit" / "cleanup" / "preservation-result.json"
    if tamper in {"receipt", "count"}:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["candidateCount"] = 1
        if tamper == "count":
            receipt["receiptSha256"] = content_hash(
                {key: value for key, value in receipt.items() if key != "receiptSha256"}
            )
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    elif tamper == "master":
        master = raw_dir / "edit" / "masters" / f"{basename}.mp4"
        metadata = master.stat()
        master.write_bytes(b"MASTER-BYTES")
        os.utime(master, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    elif tamper == "bundle":
        bundle = raw_dir / "edit" / "timeline" / "reconstruction-bundle.json"
        bundle.write_text("{}", encoding="utf-8")
    elif tamper == "added":
        (proof.parent / "new-proof.mp4").write_bytes(b"new")
    else:
        proof.unlink()
    with pytest.raises((ValueError, project_inventory.PreservedSetViolation)):
        project_inventory.verify_preservation_closure(raw_dir, basename)


def test_preservation_receipt_cannot_be_reused_for_another_master(
    preservation_project,
):
    workspace, basename, _ = preservation_project
    project_inventory.record_preservation_closure(workspace.raw_dir, basename)
    with pytest.raises(project_inventory.PreservedSetViolation, match="master"):
        project_inventory.verify_preservation_closure(
            workspace.raw_dir, "another-master"
        )


def test_preservation_cli_preserves_existing_baseline(preservation_project, tmp_path):
    workspace, basename, _ = preservation_project
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"files": {"raw.bin": 12}}), encoding="utf-8")
    # The baseline is a new root source, so bind it before native verification.
    build_reconstruction_bundle(workspace, master_basename=basename, actor="creator")
    summary = tmp_path.parent / f"{tmp_path.name}-summary.txt"
    summary.write_text("All files retained.", encoding="utf-8")
    assert (
        wrap.main(
            [
                "final",
                "--raw-dir",
                str(workspace.raw_dir),
                "--master-basename",
                basename,
                "--summary-file",
                str(summary),
                "--session-id",
                "cli-preservation",
                "--closure-mode",
                "preservation",
                "--pre",
                str(baseline),
                "--no-export",
            ]
        )
        == 0
    )
    payload = json.loads((tmp_path / "avo.wrap.json").read_text(encoding="utf-8"))
    assert payload["files"]["degradedMode"] is False
    assert payload["space"]["preCleanupProjectBytes"] == 12
    assert payload["space"]["freedBytes"] is None


def test_preservation_cli_rejects_even_zero_freed_bytes(preservation_project, tmp_path):
    workspace, basename, _ = preservation_project
    summary = tmp_path.parent / f"{tmp_path.name}-summary.txt"
    summary.write_text("Retain all.", encoding="utf-8")
    with pytest.raises(ValueError, match="no freed-bytes"):
        wrap.main(
            [
                "final",
                "--raw-dir",
                str(workspace.raw_dir),
                "--master-basename",
                basename,
                "--summary-file",
                str(summary),
                "--session-id",
                "cli-preservation",
                "--closure-mode",
                "preservation",
                "--freed-bytes",
                "0",
                "--no-export",
            ]
        )
    assert not (tmp_path / project_inventory.PRESERVATION_RECEIPT).exists()


def test_existing_receipt_is_verified_without_rewriting(preservation_project):
    workspace, basename, _ = preservation_project
    project_inventory.record_preservation_closure(workspace.raw_dir, basename)
    path = workspace.raw_dir / project_inventory.PRESERVATION_RECEIPT
    before = path.read_bytes(), path.stat().st_mtime_ns
    project_inventory.record_preservation_closure(workspace.raw_dir, basename)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_receipt_from_other_project_is_refused_before_verification(
    preservation_project, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    workspace, basename, _ = preservation_project
    project_inventory.record_preservation_closure(workspace.raw_dir, basename)
    receipt = (workspace.raw_dir / project_inventory.PRESERVATION_RECEIPT).read_text(
        encoding="utf-8"
    )
    other = tmp_path / "other"
    target = other / project_inventory.PRESERVATION_RECEIPT
    target.parent.mkdir(parents=True)
    target.write_text(receipt, encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("wrong-project receipt must fail before native media reads")

    monkeypatch.setattr(project_inventory, "_preservation_inventory", forbidden)
    with pytest.raises(project_inventory.PreservedSetViolation, match="another"):
        project_inventory.verify_preservation_closure(other, basename)


class _ReparseMetadata:
    def __init__(self, metadata):
        self._metadata = metadata
        self.st_file_attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT

    def __getattr__(self, name):
        return getattr(self._metadata, name)


class _HardLinkedMetadata(_ReparseMetadata):
    def __init__(self, metadata):
        self._metadata = metadata
        self.st_file_attributes = getattr(metadata, "st_file_attributes", 0)
        self.st_nlink = 2


@pytest.mark.parametrize(
    "output", ["avo.wrap.json", "avo.wrap.md", "edit", "edit/cleanup", "."]
)
def test_preservation_rejects_reparse_outputs_before_native_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str
):
    (tmp_path / "edit" / "cleanup").mkdir(parents=True)
    for name in (wrap.FINAL_JSON, wrap.FINAL_MD):
        (tmp_path / name).write_text("preserve existing document", encoding="utf-8")
    target = tmp_path / output
    original_lstat = Path.lstat

    def reparse_metadata(path, *args, **kwargs):
        metadata = original_lstat(path, *args, **kwargs)
        return _ReparseMetadata(metadata) if path == target else metadata

    def forbidden(*args, **kwargs):
        pytest.fail("unsafe output must be rejected before native verification")

    monkeypatch.setattr(Path, "lstat", reparse_metadata)
    monkeypatch.setattr(project_inventory, "_preservation_inventory", forbidden)
    with pytest.raises(
        project_inventory.PreservedSetViolation, match="unsafe|link|reparse"
    ):
        wrap.finalize_preservation_wrap(
            tmp_path,
            master_basename="master",
            session_id="unsafe-output",
            provider="bishop",
            summary="Not written.",
        )
    assert all(
        (tmp_path / name).read_text(encoding="utf-8") == "preserve existing document"
        for name in (wrap.FINAL_JSON, wrap.FINAL_MD)
    )


def test_preservation_rechecks_outputs_after_long_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    output = tmp_path / wrap.FINAL_JSON
    output.write_text("existing evidence", encoding="utf-8")
    active = False
    original_lstat = Path.lstat

    def reparse_metadata(path, *args, **kwargs):
        metadata = original_lstat(path, *args, **kwargs)
        return _ReparseMetadata(metadata) if active and path == output else metadata

    def verified_then_replaced(*args, **kwargs):
        nonlocal active
        active = True
        return {"rawDir": str(tmp_path)}, {
            "receiptSha256": "1" * 64,
            "master": {"sha256": "2" * 64},
            "reconstructionBundle": {"bundleSha256": "3" * 64},
        }

    monkeypatch.setattr(Path, "lstat", reparse_metadata)
    monkeypatch.setattr(
        project_inventory, "record_preservation_closure", verified_then_replaced
    )
    with pytest.raises(
        project_inventory.PreservedSetViolation, match="unsafe|link|reparse"
    ):
        wrap.finalize_preservation_wrap(
            tmp_path,
            master_basename="master",
            session_id="late-link",
            provider="bishop",
            summary="Not written.",
        )
    assert output.read_text(encoding="utf-8") == "existing evidence"


@pytest.mark.parametrize("operation", ["record", "verify"])
def test_receipt_service_rejects_reparse_parent_before_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
):
    parent = tmp_path / "edit" / "cleanup"
    parent.mkdir(parents=True)
    original_lstat = Path.lstat

    def reparse_metadata(path, *args, **kwargs):
        metadata = original_lstat(path, *args, **kwargs)
        return _ReparseMetadata(metadata) if path == parent else metadata

    def forbidden(*args, **kwargs):
        pytest.fail("receipt parent must fail before native verification")

    monkeypatch.setattr(Path, "lstat", reparse_metadata)
    monkeypatch.setattr(project_inventory, "_preservation_inventory", forbidden)
    function = (
        project_inventory.record_preservation_closure
        if operation == "record"
        else project_inventory.verify_preservation_closure
    )
    with pytest.raises(project_inventory.PreservedSetViolation, match="reparse"):
        function(tmp_path, "master")


def test_receipt_parent_is_rechecked_before_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    parent = tmp_path / "edit" / "cleanup"
    parent.mkdir(parents=True)
    active = False
    original_lstat = Path.lstat

    def reparse_metadata(path, *args, **kwargs):
        metadata = original_lstat(path, *args, **kwargs)
        return _ReparseMetadata(metadata) if active and path == parent else metadata

    def verified_then_replaced(*args, **kwargs):
        nonlocal active
        active = True
        return None, {}

    monkeypatch.setattr(Path, "lstat", reparse_metadata)
    monkeypatch.setattr(
        project_inventory, "_preservation_inventory", verified_then_replaced
    )
    with pytest.raises(project_inventory.PreservedSetViolation, match="reparse"):
        project_inventory.record_preservation_closure(tmp_path, "master")
    assert not (tmp_path / project_inventory.PRESERVATION_RECEIPT).exists()


@pytest.mark.parametrize("output", [wrap.FINAL_JSON, wrap.FINAL_MD])
def test_preservation_never_follows_real_wrap_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str
):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside evidence", encoding="utf-8")
    try:
        (tmp_path / output).symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable for this Windows account")

    def forbidden(*args, **kwargs):
        pytest.fail("symlink must fail before native verification")

    monkeypatch.setattr(project_inventory, "_preservation_inventory", forbidden)
    with pytest.raises(
        project_inventory.PreservedSetViolation, match="unsafe|link|reparse"
    ):
        wrap.finalize_preservation_wrap(
            tmp_path,
            master_basename="master",
            session_id="symlink",
            provider="bishop",
            summary="Not written.",
        )
    assert outside.read_text(encoding="utf-8") == "outside evidence"


@pytest.mark.parametrize("output", [wrap.FINAL_JSON, wrap.FINAL_MD])
def test_preservation_rejects_hard_linked_wrap_outputs_before_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str
):
    target = tmp_path / output
    target.write_text("protected bytes", encoding="utf-8")
    original_lstat = Path.lstat

    def linked_metadata(path, *args, **kwargs):
        metadata = original_lstat(path, *args, **kwargs)
        return _HardLinkedMetadata(metadata) if path == target else metadata

    def forbidden(*args, **kwargs):
        pytest.fail("hard-linked output must fail before native verification")

    monkeypatch.setattr(Path, "lstat", linked_metadata)
    monkeypatch.setattr(project_inventory, "_preservation_inventory", forbidden)
    with pytest.raises(project_inventory.PreservedSetViolation, match="unsafe|link"):
        wrap.finalize_preservation_wrap(
            tmp_path,
            master_basename="master",
            session_id="hard-link",
            provider="bishop",
            summary="Not written.",
        )
    assert target.read_text(encoding="utf-8") == "protected bytes"


def test_preservation_keeps_real_hard_link_target_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("protected target", encoding="utf-8")
    try:
        os.link(outside, tmp_path / wrap.FINAL_JSON)
    except OSError:
        pytest.skip("hard-link creation is unavailable on this filesystem")

    def forbidden(*args, **kwargs):
        pytest.fail("hard link must be rejected before native verification")

    monkeypatch.setattr(project_inventory, "_preservation_inventory", forbidden)
    with pytest.raises(project_inventory.PreservedSetViolation, match="hard-linked"):
        wrap.finalize_preservation_wrap(
            tmp_path,
            master_basename="master",
            session_id="real-hard-link",
            provider="bishop",
            summary="Not written.",
        )
    assert outside.read_text(encoding="utf-8") == "protected target"
