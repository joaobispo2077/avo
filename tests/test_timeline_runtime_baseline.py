"""Characterize timeline capabilities that have or lack production callers."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Capability:
    name: str
    production_file: str
    required_symbols: tuple[str, ...]
    runtime_integrated: bool
    missing_entry_point: str | None = None


CAPABILITIES = (
    Capability("artifact-store", "src/avo/timeline/store.py", ("ArtifactStore",), True),
    Capability("lifecycle-policy", "src/avo/timeline/lifecycle.py", ("transition",), True),
    Capability("sync-policy", "src/avo/timeline/sync.py", ("validate_sync_snapshot",), True),
    Capability("cmap-policy", "src/avo/timeline/lineage.py", ("create_cmap_revision",), True),
    Capability("projection-policy", "src/avo/timeline/projection.py", ("project_cmap_to_edl",), True),
    Capability("tracks-policy", "src/avo/timeline/tracks.py", ("resolve_tracks",), True),
    Capability("review-policy", "src/avo/timeline/review.py", ("evaluate_gate",), True),
    Capability("watch-adapter", "src/avo/adapters/understand/watch_skill.py", ("WatchSkillAdapter",), True),
    Capability("workspace-service", "src/avo/timeline/workspace.py", ("TimelineWorkspace",), True),
    Capability("sync-service", "src/avo/timeline/sync_service.py", ("SyncService",), True),
    Capability("cmap-service", "src/avo/timeline/cmap_service.py", ("CMapService",), True),
    Capability("review-runner", "src/avo/timeline/review_runner.py", ("ReviewRunner",), True),
    Capability("pipeline-coordinator", "src/avo/timeline/pipeline.py", ("TimelinePipeline",), True),
)


def _symbols(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


@pytest.mark.parametrize("capability", CAPABILITIES, ids=lambda item: item.name)
def test_runtime_capability_baseline(capability: Capability) -> None:
    found = _symbols(ROOT / capability.production_file)
    integrated = all(symbol in found for symbol in capability.required_symbols)
    assert integrated is capability.runtime_integrated, (
        f"{capability.name} baseline changed: expected runtime_integrated="
        f"{capability.runtime_integrated}, symbols={sorted(found)}, "
        f"missing production entry point={capability.missing_entry_point!r}. "
        "Update this characterization only when a vertical production test proves the caller."
    )


def test_every_non_integrated_capability_names_its_missing_entry_point() -> None:
    missing = [item for item in CAPABILITIES if not item.runtime_integrated]
    assert all(item.missing_entry_point for item in missing)
