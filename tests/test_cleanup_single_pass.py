from __future__ import annotations

import json
import os

import pytest

from avo import project_inventory
from avo.timeline import reconstruction
from avo.timeline.contracts import file_fingerprint
from test_reconstruction_bundle import canonical_project


@pytest.fixture
def cleanup_project(tmp_path):
    workspace, basename = canonical_project(tmp_path)
    keep = tmp_path / "edit" / "preview" / "approved.mp4"
    discard = tmp_path / "edit" / "cache" / "scratch.bin"
    current = tmp_path / "edit" / "inputs" / "current.bin"
    for path, data in (
        (keep, b"approved"),
        (discard, b"scratch"),
        (current, b"current"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    project = json.loads(workspace.project_path.read_text(encoding="utf-8"))
    project["cleanup"] = {"preservePaths": ["edit/preview"]}
    workspace.project_path.write_text(json.dumps(project), encoding="utf-8")
    workspace.store("tracks").append_revision(
        snapshot={"source": {"locator": str(current), **file_fingerprint(current)}},
        actor="agent",
        reason="current protected media",
    )
    bundle = reconstruction.build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    return workspace, basename, keep, discard, current, bundle


@pytest.mark.parametrize("dry_run", [True, False])
def test_cleanup_verifies_once_and_only_removes_real_disposables(
    cleanup_project, monkeypatch, dry_run
):
    workspace, basename, keep, discard, current, bundle = cleanup_project
    verify = reconstruction.verify_reconstruction_bundle
    calls = []

    def counted(*args, **kwargs):
        calls.append(args)
        return verify(*args, **kwargs)

    monkeypatch.setattr(reconstruction, "verify_reconstruction_bundle", counted)
    outcome = project_inventory.run_cleanup(
        workspace.raw_dir,
        basename,
        dry_run=dry_run,
        rimraf_runner=lambda path: path.unlink(),
        purge_session=False,
    )
    assert len(calls) == 1
    assert outcome.paths == [discard]
    assert keep.read_bytes() == b"approved"
    assert current.read_bytes() == b"current"
    assert all((workspace.raw_dir / item["path"]).is_file() for item in bundle["files"])
    assert discard.exists() is dry_run
    receipt = workspace.raw_dir / "edit" / "cleanup" / "cleanup-result.json"
    if dry_run:
        assert not receipt.exists() and outcome.freed_bytes == 0
    else:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        assert payload["status"] == "completed"
        assert payload["deleted"] == [{"path": "edit/cache/scratch.bin", "bytes": 7}]
        assert outcome.freed_bytes == payload["freedBytes"] == 7


@pytest.mark.parametrize(
    "damage",
    [
        "missing-bundle",
        "missing-source",
        "changed-source",
        "same-size-date-source",
        "missing-master",
        "changed-master",
        "same-size-date-master",
        "missing-current-input",
    ],
)
def test_cleanup_fails_before_deletion_when_verified_inputs_change(
    cleanup_project, damage
):
    workspace, basename, _, discard, current, bundle = cleanup_project
    if damage == "missing-bundle":
        target = workspace.timeline_dir / "reconstruction-bundle.json"
    elif "source" in damage:
        target = workspace.raw_dir / "raw.bin"
    elif "master" in damage:
        target = workspace.raw_dir / bundle["master"]["path"]
    else:
        target = current
    before = target.stat()
    if damage.startswith("missing"):
        target.unlink()
    else:
        target.write_bytes(target.read_bytes().upper())
        if damage.startswith("same-size-date"):
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
            assert target.stat().st_size == before.st_size
            assert target.stat().st_mtime_ns == before.st_mtime_ns
    attempted = []
    with pytest.raises(SystemExit, match="reconstruction"):
        project_inventory.run_cleanup(
            workspace.raw_dir,
            basename,
            rimraf_runner=attempted.append,
            purge_session=False,
        )
    assert attempted == [] and discard.read_bytes() == b"scratch"
    assert not (workspace.raw_dir / "edit/cleanup/cleanup-result.json").exists()


def test_cleanup_still_refuses_a_protected_target(cleanup_project, monkeypatch):
    workspace, basename, keep, _, _, _ = cleanup_project
    monkeypatch.setattr(
        project_inventory, "scan_delete_candidates", lambda *_: ([keep], 0)
    )
    attempted = []
    with pytest.raises(project_inventory.PreservedSetViolation, match="preserved"):
        project_inventory.run_cleanup(
            workspace.raw_dir,
            basename,
            rimraf_runner=attempted.append,
            purge_session=False,
        )
    assert attempted == [] and keep.read_bytes() == b"approved"


def test_cleanup_rechecks_bytes_on_a_later_independent_call(
    cleanup_project, monkeypatch
):
    workspace, basename, _, discard, _, _ = cleanup_project
    verify = reconstruction.verify_reconstruction_bundle
    calls = []

    def counted(*args, **kwargs):
        calls.append(args)
        return verify(*args, **kwargs)

    monkeypatch.setattr(reconstruction, "verify_reconstruction_bundle", counted)
    project_inventory.run_cleanup(workspace.raw_dir, basename, dry_run=True)
    source = workspace.raw_dir / "raw.bin"
    before = source.stat()
    source.write_bytes(source.read_bytes().upper())
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(SystemExit, match="reconstruction"):
        project_inventory.run_cleanup(workspace.raw_dir, basename, dry_run=True)
    assert len(calls) == 2 and discard.exists()


def test_cleanup_still_requires_the_initial_transcript(cleanup_project):
    workspace, basename, _, discard, _, _ = cleanup_project
    initial = workspace.raw_dir / "edit" / "transcripts" / "initial.json"
    initial.unlink()
    attempted = []
    with pytest.raises(SystemExit, match="initial transcript"):
        project_inventory.run_cleanup(
            workspace.raw_dir,
            basename,
            initial_transcript=initial,
            rimraf_runner=attempted.append,
            purge_session=False,
        )
    assert attempted == [] and discard.exists()
