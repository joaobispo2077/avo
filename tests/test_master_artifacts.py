from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from avo.master_artifacts import MasterArtifactError, resolve_final_masters

STEM = "demo-master-v001"
SHA = "a" * 64


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def project(tmp_path: Path) -> tuple[Path, Path]:
    raw = tmp_path / "project"
    master = raw / "edit" / "proofs" / f"{STEM}.mp4"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"media")
    write_json(
        raw / "edit" / "transcripts" / f"{STEM}.json",
        {
            "source": {
                "path": str(raw / "edit" / "native" / "window-0003.mp4"),
                "sha256": SHA,
                "sizeBytes": 5,
            }
        },
    )
    return raw, master


def descriptor(raw: Path, master: Path, **overrides: object) -> dict:
    return {
        "master": {
            "path": str(master),
            "sha256": SHA,
            "sizeBytes": master.stat().st_size,
            **overrides,
        }
    }


@pytest.mark.parametrize(
    "manifest",
    ["edit/delivery-manifest.json", "edit/delivery/final/manifesto.json"],
)
def test_explicit_export_reference_is_metadata_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: str
):
    raw, master = project(tmp_path)
    write_json(raw / manifest, descriptor(raw, master))
    original_open = Path.open

    def guard_media_open(path: Path, *args, **kwargs):
        assert path != master, "master lookup must not read media bytes"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard_media_open)
    assert resolve_final_masters(raw, STEM) == [master.resolve()]


def test_legacy_glob_matches_remain_supported(tmp_path: Path):
    raw, _ = project(tmp_path)
    masters = raw / "edit" / "masters"
    masters.mkdir()
    paths = [masters / f"{STEM}.{suffix}" for suffix in ("mp4", "mov", "mp4.bak")]
    for path in paths:
        path.write_bytes(b"legacy")
    (masters / f"{STEM}.folder").mkdir()
    assert resolve_final_masters(raw, STEM) == sorted(paths)


@pytest.mark.skipif(os.name != "nt", reason="legacy Windows glob is case-insensitive")
def test_legacy_windows_stem_matching_remains_case_insensitive(tmp_path: Path):
    raw, _ = project(tmp_path)
    master = raw / "edit" / "masters" / f"{STEM.upper()}.MP4"
    master.parent.mkdir()
    master.write_bytes(b"legacy")
    assert resolve_final_masters(raw, STEM) == [master]


def test_unreferenced_proof_is_not_a_final_master(tmp_path: Path):
    raw, master = project(tmp_path)
    assert master.is_file()
    assert resolve_final_masters(raw, STEM) == []


def test_identical_manifest_references_are_deduplicated(tmp_path: Path):
    raw, master = project(tmp_path)
    value = descriptor(raw, master)
    write_json(raw / "edit" / "delivery-manifest.json", value)
    write_json(raw / "edit" / "delivery" / "final" / "manifesto.json", value)
    assert resolve_final_masters(raw, STEM) == [master]


@pytest.mark.parametrize(
    "source",
    [
        {"sha256": "b" * 64},
        {"sha256": SHA, "sizeBytes": 6},
        {"sha256": SHA, "size_bytes": 6},
        {"sha256": SHA, "sizeBytes": 5, "size_bytes": 6},
        {"sha256": SHA, "sizeBytes": 6, "size_bytes": 5},
    ],
)
def test_transcript_identity_mismatch_fails_closed(tmp_path: Path, source: dict):
    raw, master = project(tmp_path)
    write_json(raw / "edit" / "delivery-manifest.json", descriptor(raw, master))
    write_json(
        raw / "edit" / "transcripts" / f"{STEM}.json",
        {"source": source},
    )
    with pytest.raises(MasterArtifactError):
        resolve_final_masters(raw, STEM)


@pytest.mark.parametrize(
    "sizes",
    [{}, {"sizeBytes": 5}, {"size_bytes": 5}, {"sizeBytes": 5, "size_bytes": 5}],
)
def test_transcript_size_aliases_are_optional_and_consistent(
    tmp_path: Path, sizes: dict
):
    raw, master = project(tmp_path)
    write_json(raw / "edit" / "delivery-manifest.json", descriptor(raw, master))
    write_json(
        raw / "edit" / "transcripts" / f"{STEM}.json",
        {"source": {"sha256": SHA, **sizes}},
    )
    assert resolve_final_masters(raw, STEM) == [master]


def test_stats_duration_uses_same_explicit_export_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from avo import stats

    raw, master = project(tmp_path)
    write_json(raw / "edit" / "delivery-manifest.json", descriptor(raw, master))
    probed = []

    def probe(path: Path) -> float:
        probed.append(path)
        return 101.5

    monkeypatch.setattr(stats, "media_duration", probe)
    assert stats._probe_master_duration(raw, STEM) == 101.5
    assert probed == [master]


@pytest.mark.parametrize("overrides", [{"sizeBytes": 6}, {"sha256": "bad"}])
def test_invalid_manifest_identity_fails_closed(tmp_path: Path, overrides: dict):
    raw, master = project(tmp_path)
    write_json(
        raw / "edit" / "delivery-manifest.json",
        descriptor(raw, master, **overrides),
    )
    with pytest.raises(MasterArtifactError):
        resolve_final_masters(raw, STEM)


def test_missing_referenced_master_fails_closed(tmp_path: Path):
    raw, master = project(tmp_path)
    missing = raw / "edit" / "missing" / master.name
    write_json(
        raw / "edit" / "delivery-manifest.json",
        descriptor(raw, master, path=str(missing)),
    )
    with pytest.raises(MasterArtifactError):
        resolve_final_masters(raw, STEM)


def test_distinct_paths_with_same_stem_are_ambiguous(tmp_path: Path):
    raw, master = project(tmp_path)
    other = raw / "edit" / "other" / master.name
    other.parent.mkdir()
    other.write_bytes(b"media")
    write_json(raw / "edit" / "delivery-manifest.json", descriptor(raw, master))
    write_json(
        raw / "edit" / "delivery" / "final" / "manifesto.json",
        descriptor(raw, other),
    )
    with pytest.raises(MasterArtifactError):
        resolve_final_masters(raw, STEM)


def test_conflicting_hashes_for_same_path_fail_closed(tmp_path: Path):
    raw, master = project(tmp_path)
    write_json(raw / "edit" / "delivery-manifest.json", descriptor(raw, master))
    write_json(
        raw / "edit" / "delivery" / "final" / "manifesto.json",
        descriptor(raw, master, sha256="b" * 64),
    )
    with pytest.raises(MasterArtifactError):
        resolve_final_masters(raw, STEM)


@pytest.mark.parametrize("path_kind", ["outside", "traversal"])
def test_outside_project_and_traversal_references_fail_closed(
    tmp_path: Path, path_kind: str
):
    raw, master = project(tmp_path)
    if path_kind == "outside":
        candidate = tmp_path / master.name
        candidate.write_bytes(b"media")
    else:
        candidate = raw / "edit" / "proofs" / ".." / "proofs" / master.name
    write_json(
        raw / "edit" / "delivery-manifest.json",
        descriptor(raw, master, path=str(candidate)),
    )
    with pytest.raises(MasterArtifactError):
        resolve_final_masters(raw, STEM)


@pytest.mark.parametrize("legacy", [False, True])
def test_symlink_is_never_selected(tmp_path: Path, legacy: bool):
    raw, master = project(tmp_path)
    link = raw / "edit" / ("masters" if legacy else "linked") / master.name
    link.parent.mkdir()
    try:
        link.symlink_to(master)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are unavailable for this account")
    if legacy:
        assert resolve_final_masters(raw, STEM) == []
    else:
        write_json(raw / "edit" / "delivery-manifest.json", descriptor(raw, link))
        with pytest.raises(MasterArtifactError):
            resolve_final_masters(raw, STEM)


@pytest.mark.parametrize("target", ["manifest", "transcript"])
@pytest.mark.parametrize("value", ["not-json", "[]"])
def test_malformed_documents_fail_closed(tmp_path: Path, target: str, value: str):
    raw, master = project(tmp_path)
    manifest = write_json(
        raw / "edit" / "delivery-manifest.json", descriptor(raw, master)
    )
    path = (
        manifest
        if target == "manifest"
        else raw / "edit" / "transcripts" / f"{STEM}.json"
    )
    path.write_text(value, encoding="utf-8")
    with pytest.raises(MasterArtifactError):
        resolve_final_masters(raw, STEM)


@pytest.mark.parametrize(
    "basename", ["", ".", "..", "../demo", "a/b", "a\\b", "a*", "a?", "a[0]", "C:demo"]
)
def test_unsafe_basename_is_rejected(tmp_path: Path, basename: str):
    with pytest.raises(MasterArtifactError):
        resolve_final_masters(tmp_path, basename)
