"""Library requests and paths are a trust boundary, not agent authority."""

import pytest

from avo.library.rules import LibraryError, read_request, safe_path, validate


@pytest.mark.parametrize(
    "name", ["../outside", "C:/outside", "a\\b", "clip:ads", "/x", "CON.mp4", "a/../b"]
)
def test_unsafe_relative_paths(tmp_path, name):
    with pytest.raises(LibraryError):
        safe_path(tmp_path, name)


def test_request_rejects_unknown_fields_nonfinite_and_hash_mismatch(tmp_path):
    request = tmp_path / "request.json"
    request.write_text('{"schemaVersion":1,"kind":"edits","unexpected":true}')
    with pytest.raises(LibraryError):
        read_request(request, "0" * 64)
    request.write_text('{"value":NaN}')
    with pytest.raises(LibraryError):
        read_request(request)
    with pytest.raises(LibraryError):
        validate("decision", {"approved": True})


def test_safe_path_rejects_linked_parent(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink permission unavailable")
    with pytest.raises(LibraryError):
        safe_path(tmp_path, "link/file.json")
