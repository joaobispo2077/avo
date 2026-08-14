from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from avo.timeline.contracts import content_hash
from avo.timeline.store import ArtifactStore, StoreError, atomic_write_json


class TimelineStoreTests(unittest.TestCase):
    def test_canonical_hash_ignores_mapping_order(self) -> None:
        self.assertEqual(content_hash({"b": 2, "a": 1}), content_hash({"a": 1, "b": 2}))

    def test_append_is_immutable_and_advances_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(Path(tmp) / "cmap.json")
            store.initialize(
                artifact_type="cmap", artifact_id="main", video_id="video-1",
                provider="bishop", timeline_domain="raw-source",
            )
            first = store.append_revision(
                snapshot={"segments": []}, actor="agent", reason="initial",
            )
            second = store.append_revision(
                snapshot={"segments": [{"segmentId": "s1"}]},
                actor="agent", reason="keep intro", parent_revision_id=first["revisionId"],
            )
            document = store.load()
            self.assertEqual(document["currentRevisionId"], second["revisionId"])
            self.assertEqual(len(document["revisions"]), 2)
            self.assertEqual(document["revisions"][0], first)
            self.assertNotEqual(first["contentHash"], second["contentHash"])

    def test_duplicate_revision_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(Path(tmp) / "cmap.json")
            store.initialize(
                artifact_type="cmap", artifact_id="main", video_id="video-1",
                provider="bishop", timeline_domain="raw-source",
            )
            store.append_revision(
                snapshot={}, actor="agent", reason="one", revision_id="r0001",
            )
            with self.assertRaises(StoreError):
                store.append_revision(
                    snapshot={}, actor="agent", reason="duplicate", revision_id="r0001",
                )

    def test_atomic_write_keeps_previous_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            atomic_write_json(path, {"version": 1})
            with mock.patch("pathlib.Path.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    atomic_write_json(path, {"version": 2})
            self.assertEqual(json.loads(path.read_text())["version"], 1)

    def test_canonical_index_uses_immutable_sidecars_and_cas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline" / "cmap.json"
            store = ArtifactStore(path)
            store.initialize(
                artifact_type="cmap", artifact_id="video:cmap", video_id="video",
                provider="bishop", timeline_domain="raw-source",
            )
            first = store.append_revision(snapshot={}, actor="agent", reason="one")
            raw_index = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("revisions", raw_index)
            self.assertEqual(len(raw_index["revisionRefs"]), 1)
            sidecar = path.parent / raw_index["revisionRefs"][0]["path"]
            self.assertTrue(sidecar.is_file())
            with self.assertRaisesRegex(StoreError, "compare-and-swap"):
                store.append_revision(
                    snapshot={}, actor="agent", reason="stale writer",
                    expected_head_hash="0" * 64,
                )
            self.assertEqual(store.load()["currentRevisionId"], first["revisionId"])

    def test_invalid_sidecar_hash_blocks_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline" / "cmap.json"
            store = ArtifactStore(path)
            store.initialize(
                artifact_type="cmap", artifact_id="video:cmap", video_id="video",
                provider="bishop", timeline_domain="raw-source",
            )
            store.append_revision(snapshot={}, actor="agent", reason="one")
            index = json.loads(path.read_text(encoding="utf-8"))
            sidecar = path.parent / index["revisionRefs"][0]["path"]
            value = json.loads(sidecar.read_text(encoding="utf-8")); value["reason"] = "tampered"
            sidecar.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(StoreError, "hash mismatch"):
                store.load_index()


if __name__ == "__main__":
    unittest.main()
