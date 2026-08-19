from __future__ import annotations

import unittest

from avo.timeline.lineage import persist_invalidation, stale_descendants
from avo.timeline.store import ArtifactStore


class InvalidationTests(unittest.TestCase):
    def test_cmap_stales_all_downstream(self):
        self.assertEqual(
            stale_descendants("cmap"),
            {"bmap", "tracks", "animation", "candidate", "review", "approval"},
        )

    def test_bmap_preserves_sync_and_cmap(self):
        result = stale_descendants("bmap")
        self.assertNotIn("sync-map", result)
        self.assertNotIn("cmap", result)
        self.assertIn("tracks", result)

    def test_path_move_same_hash_stales_nothing(self):
        self.assertEqual(
            stale_descendants("cmap", before_hash="a" * 64, after_hash="a" * 64), set()
        )


def test_persisted_invalidation_marks_real_descendants(tmp_path):
    stores = {}
    for kind, domain in (
        ("cmap", "raw-source"),
        ("bmap", "cmap-output"),
        ("tracks", "cmap-output"),
        ("animation", "cmap-output"),
        ("sync-map", "raw-source"),
    ):
        store = ArtifactStore(tmp_path / f"{kind}.json")
        store.initialize(
            artifact_type=kind,
            artifact_id=f"video:{kind}",
            video_id="video",
            provider="bishop",
            timeline_domain=domain,
        )
        store.append_revision(snapshot={}, actor="agent", reason="seed")
        stores[kind] = store
    report = persist_invalidation(
        stores, "cmap", before_hash="a" * 64, after_hash="b" * 64, reason="new cut"
    )
    assert {item["artifactType"] for item in report["affected"]} == {
        "bmap",
        "tracks",
        "animation",
    }
    assert stores["bmap"].load_index()["activeState"] == "stale"
    assert stores["sync-map"].load_index()["activeState"] == "valid"
