"""Locate final exports without relocating media or asserting delivery approval."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path, PureWindowsPath


class MasterArtifactError(RuntimeError):
    """A final-export reference is unsafe, inconsistent, or ambiguous."""


def _read_document(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MasterArtifactError(f"cannot read master reference: {path}") from error
    if not isinstance(document, dict):
        raise MasterArtifactError(f"invalid master reference document: {path}")
    return document


def _project_file(raw_dir: Path, path: Path) -> Path:
    resolved = path.resolve()
    if ".." in path.parts or not resolved.is_relative_to(raw_dir):
        raise MasterArtifactError(f"master reference escapes project: {path}")
    if any(part.is_symlink() for part in (path, *path.parents) if part != raw_dir):
        raise MasterArtifactError(f"master reference uses a symlink: {path}")
    if not path.is_file():
        raise MasterArtifactError(f"master reference file is missing: {path}")
    return resolved


def _master_reference(
    raw_dir: Path, basename: str, manifest: Path
) -> tuple[Path, tuple[str, int]] | None:
    document = _read_document(_project_file(raw_dir, manifest))
    master = document.get("master")
    if not isinstance(master, dict) or not isinstance(master.get("path"), str):
        return None
    path = Path(master["path"].replace("\\", "/"))
    if os.path.normcase(path.stem) != os.path.normcase(basename):
        return None
    path = _project_file(raw_dir, path if path.is_absolute() else raw_dir / path)
    identity = (master.get("sha256"), master.get("sizeBytes"))
    if (
        not isinstance(identity[0], str)
        or re.fullmatch(r"[0-9a-f]{64}", identity[0]) is None
        or type(identity[1]) is not int
        or identity[1] != path.stat().st_size
    ):
        raise MasterArtifactError(f"invalid master identity in {manifest}")
    return path, identity


def _referenced_masters(raw_dir: Path, basename: str) -> list[Path]:
    edit = raw_dir / "edit"
    native = edit / "delivery-manifest.json"
    manifests = ([native] if native.exists() else []) + sorted(
        (edit / "delivery").rglob("*manifest*.json")
    )
    references: dict[Path, tuple[str, int]] = {}
    for manifest in manifests:
        reference = _master_reference(raw_dir, basename, manifest)
        if reference is None:
            continue
        path, identity = reference
        if path in references and references[path] != identity:
            raise MasterArtifactError(f"conflicting master references: {path}")
        references[path] = identity
    if len(references) > 1:
        raise MasterArtifactError(f"ambiguous final master for basename {basename!r}")
    if references:
        _validate_transcript(raw_dir, basename, next(iter(references.values())))
    return sorted(references)


def _validate_transcript(
    raw_dir: Path, basename: str, identity: tuple[str, int]
) -> None:
    transcript = raw_dir / "edit" / "transcripts" / f"{basename}.json"
    source = _read_document(_project_file(raw_dir, transcript)).get("source")
    if (
        not isinstance(source, dict)
        or source.get("sha256") != identity[0]
        or any(
            type(source[key]) is not int or source[key] != identity[1]
            for key in ("sizeBytes", "size_bytes")
            if key in source
        )
    ):
        raise MasterArtifactError("final transcript/master reference identity mismatch")


def _validate_basename(master_basename: str) -> None:
    if (
        not master_basename
        or Path(master_basename).name != master_basename
        or PureWindowsPath(master_basename).name != master_basename
        or any(character in master_basename for character in "*?[]:")
        or master_basename in {".", ".."}
    ):
        raise MasterArtifactError("master basename must be a plain filename stem")


def resolve_final_masters(raw_dir: Path, master_basename: str) -> list[Path]:
    """Keep legacy masters; otherwise resolve an explicitly documented export.

    This metadata-only lookup does not verify media bytes or confer approval.
    Reconstruction retains its independent exact-master fingerprint check.
    """
    _validate_basename(master_basename)
    raw_dir = raw_dir.resolve()
    masters_dir = raw_dir / "edit" / "masters"
    legacy = sorted(
        _project_file(raw_dir, path)
        for path in masters_dir.glob(f"{master_basename}.*")
        if path.is_file() and not path.is_symlink()
    )
    return legacy or _referenced_masters(raw_dir, master_basename)
