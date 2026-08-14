from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from avo.timeline.lineage import create_cmap_revision, approve_cmap_revision
from avo.timeline.store import ArtifactStore, StoreError


class TimelineCMapIntegrationTests(unittest.TestCase):
    def test_revision_and_approval_bind_exact_cut_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(Path(tmp) / "cmap.json")
            store.initialize(artifact_type="cmap", artifact_id="main", video_id="v", provider="bishop", timeline_domain="raw-source")
            snapshot = {"sources": [{"sourceId": "cam", "kind": "raw", "fingerprint": {"sha256": "a" * 64, "sizeBytes": 1}}], "segments": [{"segmentId": "s1", "sourceId": "cam", "in": {"ticks": 0, "timebase": {"num": 1, "den": 1000}, "domain": "raw-source", "sourceId": "cam"}, "out": {"ticks": 1, "timebase": {"num": 1, "den": 1000}, "domain": "raw-source", "sourceId": "cam"}, "reason": "keep"}]}
            revision = create_cmap_revision(store, snapshot, actor="agent", reason="initial")
            approve_cmap_revision(store, revision["revisionId"], revision["contentHash"], "c" * 64)
            self.assertEqual(store.load()["approvedRevisionId"], revision["revisionId"])
            with self.assertRaises(StoreError):
                approve_cmap_revision(store, revision["revisionId"], revision["contentHash"], "short")


if __name__ == "__main__":
    unittest.main()
