from __future__ import annotations

import pytest

from avo.timeline.lineage import LineageError, validate_cmap_snapshot
from avo.timeline.models import Timebase, TimelineDomain, TimeValue
from avo.timeline.store import ArtifactStore, StoreError


def test_invalid_timebases_rejected():
    for num, den in ((0, 1), (1, 0), (-1, 1)):
        with pytest.raises(ValueError):
            Timebase(num, den)


def test_source_domain_requires_source_id():
    with pytest.raises(ValueError):
        TimeValue(0, Timebase(1, 1000), TimelineDomain.RAW_SOURCE)


def test_non_monotonic_ranges_rejected():
    snapshot = {
        "sources": [
            {
                "sourceId": "raw",
                "kind": "raw",
                "fingerprint": {"sha256": "a" * 64, "sizeBytes": 1},
            }
        ],
        "segments": [
            {
                "segmentId": "s",
                "sourceId": "raw",
                "in": {
                    "ticks": 10,
                    "timebase": {"num": 1, "den": 1000},
                    "domain": "raw-source",
                    "sourceId": "raw",
                },
                "out": {
                    "ticks": 5,
                    "timebase": {"num": 1, "den": 1000},
                    "domain": "raw-source",
                    "sourceId": "raw",
                },
                "reason": "bad",
            }
        ],
    }
    with pytest.raises(LineageError):
        validate_cmap_snapshot(snapshot)


def test_revision_parent_cycle_cannot_be_created(tmp_path):
    store = ArtifactStore(tmp_path / "cmap.json")
    store.initialize(
        artifact_type="cmap",
        artifact_id="x",
        video_id="v",
        provider="bishop",
        timeline_domain="raw-source",
    )
    with pytest.raises(StoreError):
        store.append_revision(
            snapshot={},
            actor="a",
            reason="cycle",
            parent_revision_id="r0001",
            revision_id="r0001",
        )
