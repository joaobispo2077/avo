"""Real no-replace moves against disposable local storage, never live footage."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from avo.adapters.media import library_moves
from avo.library.rules import LibraryError, source_lock


@pytest.fixture
def native_root(tmp_path):
    result = library_moves.capability(tmp_path)
    if not result["available"]:
        pytest.skip(result["reason"])
    return tmp_path


def source(root, relative="original.mp4"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"original fixture media\x00\x01\x02")
    return path, source_lock(path)


def test_native_move_and_reverse_keep_bytes_and_exact_file_identity(native_root):
    original, expected = source(native_root)
    data = original.read_bytes()
    moved = library_moves.move_no_replace(
        native_root, "original.mp4", "organized/camera/renamed.mp4", expected
    )
    destination = native_root / "organized/camera/renamed.mp4"

    assert not original.exists()
    assert destination.read_bytes() == data
    for key in ("sha256", "sizeBytes", "device", "fileId"):
        assert moved[key] == expected[key]
    restored = library_moves.move_no_replace(
        native_root,
        "organized/camera/renamed.mp4",
        "original.mp4",
        source_lock(destination),
    )
    assert original.read_bytes() == data
    assert not destination.exists()
    assert restored["fileId"] == expected["fileId"]


def test_existing_destination_is_never_replaced(native_root):
    original, expected = source(native_root)
    destination = native_root / "occupied.mp4"
    destination.write_bytes(b"must survive")
    before = original.read_bytes()

    with pytest.raises(LibraryError) as error:
        library_moves.move_no_replace(
            native_root, "original.mp4", "occupied.mp4", expected
        )

    assert error.value.code == "LIB_DESTINATION_EXISTS"
    assert original.read_bytes() == before
    assert destination.read_bytes() == b"must survive"


def test_changed_source_cannot_use_an_old_lock(native_root):
    original, expected = source(native_root)
    original.write_bytes(b"changed after approval")

    with pytest.raises(LibraryError) as error:
        library_moves.move_no_replace(native_root, "original.mp4", "new.mp4", expected)

    assert error.value.code == "LIB_SOURCE_CHANGED"
    assert original.read_bytes() == b"changed after approval"
    assert not (native_root / "new.mp4").exists()


def test_destination_created_after_precheck_is_still_never_replaced(
    native_root, monkeypatch
):
    original, expected = source(native_root)
    destination = native_root / "new.mp4"
    rename = library_moves._rename_handle

    def occupy_before_native_call(*args, **kwargs):
        destination.write_bytes(b"arrived after precheck")
        return rename(*args, **kwargs)

    monkeypatch.setattr(library_moves, "_rename_handle", occupy_before_native_call)

    with pytest.raises(LibraryError) as error:
        library_moves.move_no_replace(native_root, "original.mp4", "new.mp4", expected)

    assert error.value.code == "LIB_DESTINATION_EXISTS"
    assert destination.read_bytes() == b"arrived after precheck"
    assert source_lock(original) == expected


def test_hardlinked_source_is_refused(native_root):
    original, expected = source(native_root)
    alias = native_root / "alias.mp4"
    os.link(original, alias)

    with pytest.raises(LibraryError) as error:
        library_moves.move_no_replace(native_root, "original.mp4", "new.mp4", expected)

    assert error.value.code == "LIB_ROOT_UNSAFE"
    assert original.read_bytes() == alias.read_bytes()
    assert not (native_root / "new.mp4").exists()


@pytest.mark.parametrize("relative", ["../escape.mp4", "C:/escape.mp4", "clip:ads"])
def test_unsafe_destination_is_refused(native_root, relative):
    original, expected = source(native_root)

    with pytest.raises(LibraryError) as error:
        library_moves.move_no_replace(native_root, "original.mp4", relative, expected)

    assert error.value.code == "LIB_ROOT_UNSAFE"
    assert original.exists()


def test_linked_destination_parent_is_refused(native_root):
    original, expected = source(native_root)
    actual = native_root / "actual"
    actual.mkdir()
    link = native_root / "linked"
    try:
        link.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not grant symbolic-link creation")

    with pytest.raises(LibraryError) as error:
        library_moves.move_no_replace(
            native_root, "original.mp4", "linked/new.mp4", expected
        )

    assert error.value.code == "LIB_ROOT_UNSAFE"
    assert original.exists()
    assert not (actual / "new.mp4").exists()


def test_linked_source_is_refused(native_root):
    original, expected = source(native_root)
    link = native_root / "linked.mp4"
    try:
        link.symlink_to(original)
    except OSError:
        pytest.skip("Host does not grant symbolic-link creation")

    with pytest.raises(LibraryError) as error:
        library_moves.move_no_replace(native_root, "linked.mp4", "new.mp4", expected)

    assert error.value.code == "LIB_ROOT_UNSAFE"
    assert original.exists()
    assert not (native_root / "new.mp4").exists()


def test_case_only_move_is_refused(native_root):
    original, expected = source(native_root)

    with pytest.raises(LibraryError) as error:
        library_moves.move_no_replace(
            native_root, "original.mp4", "ORIGINAL.mp4", expected
        )

    assert error.value.code == "LIB_ROOT_UNSAFE"
    assert original.exists()


def test_other_platform_refuses_instead_of_copying(tmp_path, monkeypatch):
    original, expected = source(tmp_path)
    monkeypatch.setattr(library_moves.sys, "platform", "linux")

    assert library_moves.capability(tmp_path)["available"] is False
    with pytest.raises(LibraryError) as error:
        library_moves.move_no_replace(tmp_path, "original.mp4", "new.mp4", expected)

    assert error.value.code == "LIB_MOVE_UNSUPPORTED"
    assert original.exists()
    assert not (tmp_path / "new.mp4").exists()


def test_network_roots_are_explicitly_unavailable():
    result = library_moves.capability(Path(r"\\fixture-server\share\library"))
    assert result["available"] is False
    assert result["reason"]


def test_locked_source_and_parents_cannot_be_replaced_during_rename(
    native_root, monkeypatch
):
    original, expected = source(native_root, "camera/original.mp4")
    target_parent = native_root / "organized"
    target_parent.mkdir()
    rename = library_moves._rename_handle
    denials = []

    def inspect_locks(*args, **kwargs):
        for path in (original, original.parent, target_parent, native_root):
            with pytest.raises(OSError):
                path.rename(path.with_name(path.name + "-replaced"))
            denials.append(path)
        with pytest.raises(OSError):
            original.write_bytes(b"unapproved write")
        return rename(*args, **kwargs)

    monkeypatch.setattr(library_moves, "_rename_handle", inspect_locks)
    result = library_moves.move_no_replace(
        native_root, "camera/original.mp4", "organized/new.mp4", expected
    )

    assert len(denials) == 4
    assert result["sha256"] == expected["sha256"]
    assert (target_parent / "new.mp4").exists()
