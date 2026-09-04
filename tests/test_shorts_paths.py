from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.shorts_paths import (
    ShortsPathError,
    register_batch,
    resolve_shorts_batch_paths,
    snapshot_external_file,
)


def test_default_and_nested_roots_have_one_canonical_tree(tmp_path: Path) -> None:
    default = resolve_shorts_batch_paths(tmp_path, "batch-one")
    nested = resolve_shorts_batch_paths(
        tmp_path, "batch-two", batch_dir="campaign/batch-two"
    )
    assert default.batch_root == tmp_path / "edit" / "shorts" / "batch-one"
    assert nested.batch_root == tmp_path / "edit" / "shorts" / "campaign" / "batch-two"
    assert default.request_root == default.batch_root
    assert default.status_path == default.batch_root / "plans" / "shorts.status.json"
    assert default.transcripts_dir == default.delivery_dir / "transcripts"


def test_windows_and_posix_relative_overrides_normalize_to_same_root(
    tmp_path: Path,
) -> None:
    windows = resolve_shorts_batch_paths(
        tmp_path, "batch-one", batch_dir=r"campaign\batch-one"
    )
    posix = resolve_shorts_batch_paths(
        tmp_path, "batch-one", batch_dir="campaign/batch-one"
    )
    assert windows.batch_root == posix.batch_root
    assert windows.payload()["batchRoot"] == str(posix.batch_root)


def test_traversal_batch_mismatch_and_v11_plan_escape_are_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(ShortsPathError, match="inside"):
        resolve_shorts_batch_paths(tmp_path, "demo", batch_dir="../demo")
    with pytest.raises(ShortsPathError, match="match"):
        resolve_shorts_batch_paths(tmp_path, "demo", batch_dir="campaign/other")
    paths = resolve_shorts_batch_paths(tmp_path, "demo")
    with pytest.raises(ShortsPathError, match="v1.1 plan"):
        paths.validate_plan_path(tmp_path / "plan.json", plan_version="1.1")


def test_index_registration_is_atomic_and_rejects_collision(tmp_path: Path) -> None:
    paths = resolve_shorts_batch_paths(tmp_path, "demo")
    plan_hash = "a" * 64
    index = register_batch(paths, plan_hash=plan_hash)
    assert index["batches"][0]["batchId"] == "demo"
    assert index["batches"][0]["planHash"] == plan_hash
    assert json.loads(paths.index_path.read_text(encoding="utf-8")) == index
    other_root = tmp_path / "edit" / "shorts" / "nested" / "demo"
    with pytest.raises(ShortsPathError, match="already registered"):
        register_batch(
            resolve_shorts_batch_paths(tmp_path, "demo", batch_dir=other_root)
        )


def test_register_without_plan_preserves_existing_plan_identity(tmp_path: Path) -> None:
    paths = resolve_shorts_batch_paths(tmp_path, "demo")
    register_batch(paths, plan_hash="a" * 64)
    index = register_batch(paths)
    assert index["batches"][0]["planHash"] == "a" * 64


def test_corrupt_index_is_never_silently_replaced(tmp_path: Path) -> None:
    paths = resolve_shorts_batch_paths(tmp_path, "demo")
    paths.index_path.parent.mkdir(parents=True)
    paths.index_path.write_text('{"batches":"wrong"}', encoding="utf-8")
    with pytest.raises(ShortsPathError, match="invalid Shorts index"):
        register_batch(paths)


def test_legacy_inference_and_immutable_external_snapshot(tmp_path: Path) -> None:
    legacy = tmp_path / "edit" / "shorts" / "legacy" / "delivery"
    paths = resolve_shorts_batch_paths(tmp_path, "legacy", legacy_output=legacy)
    assert paths.batch_root == legacy.parent
    assert paths.root_source == "legacy-output"
    source = tmp_path / "external.json"
    source.write_text('{"request":1}', encoding="utf-8")
    first = snapshot_external_file(
        source, paths.batch_root / "shorts.request-v001.json"
    )
    assert len(first["sha256"]) == 64
    source.write_text('{"request":2}', encoding="utf-8")
    with pytest.raises(ShortsPathError, match="collision"):
        snapshot_external_file(source, paths.batch_root / "shorts.request-v001.json")
