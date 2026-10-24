"""Opt-in, read-only learning-corpus checks; no private paths in generic CI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from avo.direction.sources import collect_sources

pytestmark = pytest.mark.project


@pytest.fixture
def provider_root() -> Path:
    supplied = os.environ.get("AVO_DIRECTION_PROVIDER_ROOT")
    if not supplied:
        pytest.skip(
            "Set AVO_DIRECTION_PROVIDER_ROOT for an explicitly selected corpus."
        )
    root = Path(supplied).expanduser().resolve()
    assert root.is_dir()
    assert (root / "learndowns/index.json").is_file()
    return root


def _metadata(root: Path) -> dict:
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in (root / "learndowns").rglob("*")
        if path.is_file()
    }


def test_selected_bishop_learning_corpus_is_complete_without_media_or_mutation(
    provider_root,
):
    before = _metadata(provider_root)
    manifest = collect_sources(provider_root, "bishop")
    assert _metadata(provider_root) == before
    coverage = manifest["coverage"]
    assert coverage["discovered"] >= 13
    assert coverage["distinctProjects"] >= 11
    if coverage["discovered"] == 13:
        assert coverage["distinctProjects"] == 11
    assert (
        sum(coverage[key] for key in ("included", "related", "excluded", "unavailable"))
        == coverage["discovered"]
    )
    assert all(entry["reason"] for entry in manifest["entries"])
    assert not manifest["coverage"]["unavailable"]
    assert "legacy-narrative" in {entry["layout"] for entry in manifest["entries"]}
    assert "structured-catalog" in {
        document["role"]
        for entry in manifest["entries"]
        for document in entry["documents"]
    }
    assert not any(
        "rawDir" in record or "packageLocator" in record
        for record in manifest["evidenceRecords"]
    )
