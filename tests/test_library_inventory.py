"""Inventory is scoped metadata discovery, never source admission or inference."""

import shutil

import pytest

from avo import transcribe
from avo.library import rules
from avo.library.service import LibraryService
from library_fixtures import install_provider, make_library


@pytest.fixture
def library(tmp_path, monkeypatch, repo_root):
    install = tmp_path / "install"
    install_provider(install)
    schemas = install / "schemas"
    schemas.mkdir(exist_ok=True)
    shutil.copyfile(
        repo_root / "schemas" / "avo.library.schema.json",
        schemas / "avo.library.schema.json",
    )
    monkeypatch.setenv("AVO_ROOT", str(install))
    fixture = make_library(tmp_path / "footage", count=6)
    fixture.probe.results = {
        path: {"durationSeconds": 10.0, "audio": True} for path in fixture.files
    }
    service = LibraryService(fixture.root, "example", probe=fixture.probe)
    return service, fixture


def recordings(service, result):
    return {
        record["path"]: record
        for record in service.store.get(result["inventoryRef"])["recordings"]
    }


def test_default_scan_is_flat_and_metadata_only(library, monkeypatch):
    service, fixture = library
    original = {path: path.read_bytes() for path in fixture.files}

    def forbidden(*_args, **_kwargs):
        pytest.fail("inventory must not hash sources or start inference")

    monkeypatch.setattr(rules, "source_lock", forbidden)
    monkeypatch.setattr(transcribe, "source_fingerprint", forbidden)
    monkeypatch.setattr(transcribe, "transcribe_one", forbidden)
    result = service.scan()
    inventory = service.store.get(result["inventoryRef"])

    assert set(recordings(service, result)) == {"take-0000.mp4", "take-0001.mp4"}
    assert set(fixture.probe.calls) == {
        path for path in fixture.files if path.parent == fixture.root
    }
    assert inventory["scope"]["recursive"] is False
    assert result["summary"] == inventory["summary"]
    assert result["summary"] == {
        "total": 2,
        "bytes": sum(
            path.stat().st_size for path in fixture.files if path.parent == fixture.root
        ),
        "knownDurationSeconds": 20.0,
        "unknownDuration": 0,
        "reused": 0,
        "failed": 0,
    }
    assert result["proposalRef"] is not None
    assert service.status()["refs"]["inventory"] == result["inventoryRef"]
    assert all(path.read_bytes() == data for path, data in original.items())
    assert not (fixture.root / "edit" / "library" / "transcripts").exists()


def test_explicit_recursive_scan_excludes_generated_outputs(library):
    service, fixture = library
    for folder in (
        "edit/preview",
        "edit/masters",
        "edit/proxies",
        "camera-a/edit/cache",
    ):
        path = fixture.root / folder / "generated.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"generated output")
    (fixture.root / "notes.txt").write_text("not footage", encoding="utf-8")

    result = service.scan(recursive=True)
    inventory = service.store.get(result["inventoryRef"])
    rows = recordings(service, result)

    assert set(rows) == {
        path.relative_to(fixture.root).as_posix() for path in fixture.files
    }
    assert set(fixture.probe.calls) == set(fixture.files)
    assert inventory["scope"]["recursive"] is True
    assert len({row["id"] for row in rows.values()}) == len(fixture.files)
    assert rows["camera-a/take-0000.mp4"]["id"] != rows["camera-b/take-0000.mp4"]["id"]
    assert all(row["originalPath"] == path for path, row in rows.items())


def test_unchanged_refresh_reuses_metadata_and_stable_identity(library, monkeypatch):
    service, fixture = library
    first = service.scan(recursive=True)
    before = recordings(service, first)
    fixture.probe.calls.clear()

    def forbidden(*_args, **_kwargs):
        pytest.fail("unchanged refresh repeated expensive preparation")

    monkeypatch.setattr(rules, "source_lock", forbidden)
    monkeypatch.setattr(transcribe, "source_fingerprint", forbidden)
    monkeypatch.setattr(transcribe, "transcribe_one", forbidden)
    repeated = service.scan(recursive=True)
    after = recordings(service, repeated)

    assert fixture.probe.calls == []
    assert repeated["summary"]["reused"] == len(fixture.files)
    assert set(after) == set(before)
    assert {
        path: (row["id"], row["version"], row["metadata"])
        for path, row in after.items()
    } == {
        path: (row["id"], row["version"], row["metadata"])
        for path, row in before.items()
    }


def test_refresh_reprobes_only_changed_recording(library):
    service, fixture = library
    first = service.scan(recursive=True)
    before = recordings(service, first)
    changed = fixture.files[1]
    changed.write_bytes(b"changed recording with a different size")
    fixture.probe.results[changed] = {"durationSeconds": 23.0, "audio": False}
    fixture.probe.calls.clear()

    refreshed = service.scan(recursive=True)
    after = recordings(service, refreshed)
    relative = changed.relative_to(fixture.root).as_posix()

    assert fixture.probe.calls == [changed]
    assert after[relative]["id"] == before[relative]["id"]
    assert after[relative]["version"] != before[relative]["version"]
    assert after[relative]["metadata"]["durationSeconds"] == 23.0
    assert after[relative]["observation"]["sizeBytes"] == changed.stat().st_size
    assert all(after[path] == row for path, row in before.items() if path != relative)
    assert recordings(service, first) == before


def test_missing_recording_stays_discoverable_and_new_file_gets_new_identity(library):
    service, fixture = library
    first = service.scan(recursive=True)
    before = recordings(service, first)
    missing = fixture.files[1]
    missing_relative = missing.relative_to(fixture.root).as_posix()
    missing.unlink()
    added = fixture.root / "new-take.mp4"
    added.write_bytes(b"new recording")
    fixture.probe.results[added] = {"durationSeconds": None, "audio": True}
    fixture.probe.calls.clear()

    refreshed = service.scan(recursive=True)
    after = recordings(service, refreshed)

    assert set(after) == {*before, "new-take.mp4"}
    assert after[missing_relative]["id"] == before[missing_relative]["id"]
    assert after[missing_relative]["availability"] == "missing"
    assert after["new-take.mp4"]["id"] not in {row["id"] for row in before.values()}
    assert after["new-take.mp4"]["metadata"]["durationSeconds"] is None
    assert fixture.probe.calls == [added]


@pytest.mark.parametrize(
    "failure",
    [ValueError("corrupt container"), PermissionError("recording unreadable")],
)
def test_probe_failure_is_per_file_and_preserves_good_metadata(library, failure):
    service, fixture = library
    damaged = fixture.files[1]
    fixture.probe.results[damaged] = failure

    result = service.scan(recursive=True)
    rows = recordings(service, result)
    damaged_relative = damaged.relative_to(fixture.root).as_posix()

    assert len(rows) == len(fixture.files)
    assert result["summary"]["failed"] == 1
    assert result["summary"]["unknownDuration"] == 1
    assert result["summary"]["knownDurationSeconds"] == 50.0
    assert rows[damaged_relative]["metadata"].get("durationSeconds") is None
    assert str(failure) in rows[damaged_relative]["metadata"]["error"]
    assert all(
        row["metadata"]["durationSeconds"] == 10.0
        and row["availability"] == "available"
        for path, row in rows.items()
        if path != damaged_relative
    )
    assert service.status()["refs"]["inventory"] == result["inventoryRef"]


def test_failed_probe_after_change_keeps_old_inventory_and_marks_current_unknown(
    library,
):
    service, fixture = library
    first = service.scan(recursive=True)
    before = recordings(service, first)
    damaged = fixture.files[1]
    relative = damaged.relative_to(fixture.root).as_posix()
    damaged.write_bytes(b"changed corrupt recording")
    fixture.probe.results[damaged] = ValueError("changed recording cannot be probed")
    fixture.probe.calls.clear()

    refreshed = service.scan(recursive=True)
    after = recordings(service, refreshed)

    assert fixture.probe.calls == [damaged]
    assert after[relative]["id"] == before[relative]["id"]
    assert after[relative]["metadata"].get("durationSeconds") is None
    assert after[relative]["version"] != before[relative]["version"]
    assert recordings(service, first) == before


def test_recursive_scan_does_not_follow_loop_or_outside_link(library, tmp_path):
    service, fixture = library
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.mp4").write_bytes(b"outside selected scope")
    try:
        (fixture.root / "loop").symlink_to(fixture.root, target_is_directory=True)
        (fixture.root / "outside-link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("native directory links require privileges on this platform")

    result = service.scan(recursive=True)

    assert set(recordings(service, result)) == {
        path.relative_to(fixture.root).as_posix() for path in fixture.files
    }
    assert len(fixture.probe.calls) == len(fixture.files)
