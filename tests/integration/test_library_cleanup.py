"""Cleanup must explicitly retain library authority and recovery evidence."""

import json

import pytest

from avo.library.retention import library_paths, retention_plan
from avo.library.rules import LibraryError
from avo.library.service import LibraryService
from library_fixtures import install_provider

pytestmark = pytest.mark.integration


def test_cleanup_requires_reviewed_exact_retention(tmp_path, monkeypatch):
    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    root.mkdir()
    (root / "xpto-01.mp4").write_bytes(b"raw")
    service = LibraryService(root, "example", probe=lambda _: {"durationSeconds": 1})
    service.scan()
    project = root / "avo.project.json"
    project.write_text(json.dumps({"provider": "example", "rawDir": str(root)}))
    plan = retention_plan(root)
    assert "edit/library-index.json" in plan["requiredPaths"]
    assert "edit/library" not in plan["requiredPaths"]
    with pytest.raises(LibraryError, match="retention"):
        library_paths(root)
    project.write_text(
        json.dumps(
            {
                "provider": "example",
                "rawDir": str(root),
                "cleanup": {"preservePaths": plan["requiredPaths"]},
            }
        )
    )
    protected = library_paths(root)
    assert root / "edit/library-index.json" in protected
    assert all("/review/" not in p.as_posix() for p in protected)
    assert (root / "xpto-01.mp4").read_bytes() == b"raw"


def test_closed_root_refuses_new_metadata_and_nonlibrary_is_unchanged(
    tmp_path, monkeypatch
):
    assert library_paths(tmp_path) == []
    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    root.mkdir()
    service = LibraryService(root, "example")
    receipt = root / "edit/cleanup/preservation-result.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("{}")
    with pytest.raises(LibraryError, match="Closed"):
        service.scan()
    assert receipt.read_text() == "{}"


def test_real_cleanup_keeps_declared_library_and_discards_regenerated_views(
    tmp_path, monkeypatch, repo_root
):
    import shutil

    from avo import project_inventory
    from avo.timeline.reconstruction import _required_files

    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    shutil.copytree(repo_root / "tests/fixtures/stats-project", root)
    project = {
        "schemaVersion": "1.0.0",
        "videoId": "library-cleanup",
        "provider": "example",
        "rawDir": str(root),
    }
    (root / "avo.project.json").write_text(json.dumps(project))
    service = LibraryService(root, "example", probe=lambda _: {"durationSeconds": 1})
    service.scan(recursive=True)
    project["cleanup"] = {"preservePaths": retention_plan(root)["requiredPaths"]}
    (root / "avo.project.json").write_text(json.dumps(project))
    protected = {p: p.read_bytes() for p in library_paths(root)}
    assert set(protected) <= _required_files(root, []).keys()
    outcome = project_inventory.run_cleanup(
        root,
        "20260801-demo-master-v001",
        dry_run=False,
        rimraf_runner=lambda p: p.unlink(),
        purge_session=False,
    )
    assert outcome.leftover == 0
    assert all(p.read_bytes() == data for p, data in protected.items())
    assert not list((root / "edit/library/review").glob("*.html"))
    assert service.status()["refs"]["inventory"]
    with pytest.raises(LibraryError, match="Closed"):
        service.scan()
