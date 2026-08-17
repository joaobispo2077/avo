"""Unit tests for compact_cleanup_result (agent-facing inventory/cleanup JSON)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from avo.project_inventory import compact_cleanup_result


def test_compact_result_samples_and_omits_full_path_arrays() -> None:
    candidates = [f"edit/preview/file-{i}.mp4" for i in range(220)]
    payload = compact_cleanup_result(
        status="dry-run",
        candidates=candidates,
        preserved_count=12,
        leftover_candidates=4,
        space={
            "preCleanupProjectBytes": 100,
            "deleteCandidateBytes": 80,
            "preservedBytes": 20,
            "freedBytes": None,
        },
        verify_errors=[],
        session_id="sess",
        scratch_report="scratch/report.json",
        scratch_meta="scratch/meta.json",
    )
    assert payload["status"] == "dry-run"
    assert payload["candidateCount"] == 220
    assert payload["deletedCount"] == 0
    assert payload["preservedCount"] == 12
    assert payload["leftoverCandidates"] == 4
    assert len(payload["candidateSample"]) <= 50
    assert payload["verifyErrors"] == []
    assert payload["sessionId"] == "sess"
    assert payload["scratchReport"].endswith("report.json")
    assert payload["scratchMeta"].endswith("meta.json")
    assert "deleteCandidates" not in payload
    assert "deleted" not in payload


def test_compact_result_full_paths_includes_complete_lists() -> None:
    candidates = [f"edit/preview/file-{i}.mp4" for i in range(60)]
    deleted = [f"edit/preview/gone-{i}.mp4" for i in range(12)]
    payload = compact_cleanup_result(
        status="executed",
        candidates=candidates,
        deleted=deleted,
        full_paths=True,
        candidate_count=60,
        deleted_count=12,
    )
    assert payload["deleteCandidates"] == candidates
    assert payload["deleted"] == deleted
    assert payload["deletedSample"] == deleted
    assert payload["candidateCount"] == 60
