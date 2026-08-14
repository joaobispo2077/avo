from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from avo.timeline.migration import migrate_legacy_edl


class TimelineMigrationTests(unittest.TestCase):
    def test_dry_run_is_idempotent_and_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.mp4"
            source.write_bytes(b"raw")
            edl_path = root / "edl.json"
            edl_path.write_text(json.dumps({
                "version": 3, "story_map_approval": "approved",
                "sources": {"cam": "raw.mp4"},
                "ranges": [{"source": "cam", "start": 0.0, "end": 1.0}],
            }))
            target = root / "timeline" / "cmap.json"
            first = migrate_legacy_edl(edl_path, target, video_id="v", provider="bishop", dry_run=True)
            second = migrate_legacy_edl(edl_path, target, video_id="v", provider="bishop", dry_run=True)
            self.assertEqual(first["artifact"], second["artifact"])
            self.assertFalse(target.exists())
            self.assertEqual(first["approvalStatus"], "unknown")

    def test_apply_preserves_original_and_rerun_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw.mp4").write_bytes(b"raw")
            edl_path = root / "edl.json"
            edl_path.write_text(json.dumps({
                "version": 2, "story_map_approval": "approved",
                "sources": {"cam": "raw.mp4"},
                "ranges": [{"source": "cam", "start": 0, "end": 1}],
            }))
            target = root / "timeline" / "cmap.json"
            one = migrate_legacy_edl(edl_path, target, video_id="v", provider="bishop", dry_run=False)
            two = migrate_legacy_edl(edl_path, target, video_id="v", provider="bishop", dry_run=False)
            self.assertTrue(target.is_file())
            self.assertTrue(edl_path.is_file())
            self.assertTrue(two["idempotent"])
            self.assertEqual(one["artifact"]["revisions"][0]["contentHash"], two["artifact"]["revisions"][0]["contentHash"])


if __name__ == "__main__":
    unittest.main()
