"""Windows WSL rawDir resolver tests (mocked platform + exists)."""

from __future__ import annotations

from pathlib import Path

import pytest

from avo.timeline.workspace import WorkspaceError, resolve_project_raw_dir


def test_maps_wsl_mnt_path_when_exists() -> None:
    declared = "/mnt/h/bishop/pcrecordings/example"

    def fake_exists(path: Path) -> bool:
        text = str(path).replace("/", "\\").lower()
        return "bishop" in text and "example" in text and "h:" in text

    result = resolve_project_raw_dir(
        None,
        declared,
        platform="win32",
        exists=fake_exists,
    )
    text = str(result).replace("/", "\\")
    assert "H:" in text or text.lower().startswith("h:")
    assert "bishop" in text.lower()
    assert "example" in text.lower()
    assert "\\mnt\\" not in text.lower()
    assert "/mnt/" not in str(result).replace("\\", "/")


def test_parent_fallback_when_mapped_missing_and_edit_exists(tmp_path: Path) -> None:
    footage = tmp_path / "project"
    (footage / "edit").mkdir(parents=True)
    project = footage / "avo.project.json"
    project.write_text("{}", encoding="utf-8")

    def fake_exists(path: Path) -> bool:
        try:
            return Path(path).resolve() == (footage / "edit").resolve()
        except OSError:
            return False

    result = resolve_project_raw_dir(
        project,
        "/mnt/h/missing/footage",
        platform="win32",
        exists=fake_exists,
    )
    assert result.resolve() == footage.resolve()


def test_fail_closed_names_both_attempts(tmp_path: Path) -> None:
    footage = tmp_path / "not-footage"
    footage.mkdir()
    project = footage / "avo.project.json"
    project.write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="rawDir does not exist") as exc:
        resolve_project_raw_dir(
            project,
            "/mnt/h/missing/footage",
            platform="win32",
            exists=lambda _path: False,
        )
    message = str(exc.value)
    assert "missing" in message or "H:" in message
    assert str(footage) in message


def test_non_mnt_paths_are_not_invented_on_windows() -> None:
    from avo.timeline.workspace import map_wsl_mnt_path

    declared = "/home/ubuntu/footage"
    mapped = map_wsl_mnt_path(declared, platform="win32")
    assert mapped == Path(declared)
    result = resolve_project_raw_dir(
        None,
        declared,
        platform="win32",
        exists=lambda _path: True,
    )
    assert "mnt" not in str(result).replace("\\", "/").lower()
