"""Tests for src/avo/scratch.py and learndown scratch lifecycle."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from avo import scratch
from avo.scratch import ScratchError


class ScratchTests(unittest.TestCase):
    def test_scratch_path_lands_under_kind_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(scratch, "tmp_dir", return_value=root):
                for kind in scratch.SCRATCH_KINDS:
                    path = scratch.scratch_path(kind, "sess-1", "frame.png")
                    self.assertEqual(
                        path, (root / kind / "sess-1" / "frame.png").resolve()
                    )
                    self.assertTrue(path.parent.is_dir())

    def test_scratch_path_rejects_unknown_kind_and_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(scratch, "tmp_dir", return_value=root):
                with self.assertRaises(ScratchError) as unknown:
                    scratch.scratch_path("not-a-kind", "sess-1")
                self.assertIn("avo.scratch", str(unknown.exception))
                self.assertIn("tmp_dir", str(unknown.exception))
                with self.assertRaises(ScratchError):
                    scratch.scratch_path("qc", "")
                with self.assertRaises(ScratchError):
                    scratch.scratch_path("qc", "..")
                with self.assertRaises(ScratchError):
                    scratch.scratch_path("qc", "sess-1", "..", "escape.png")
                with self.assertRaises(ScratchError):
                    scratch.scratch_path("qc", "sess-1", str(root / "outside.png"))

    def test_purge_session_tmp_removes_all_kinds_and_leaves_other_sessions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(scratch, "tmp_dir", return_value=root):
                keep = scratch.scratch_path("qc", "sess-keep", "a.bin")
                keep.write_bytes(b"keep")
                for kind in scratch.SCRATCH_KINDS:
                    target = scratch.scratch_path(kind, "sess-1", "drop.bin")
                    target.write_bytes(b"drop")
                self.assertTrue(scratch.purge_session_tmp("sess-1"))
                for kind in scratch.SCRATCH_KINDS:
                    self.assertFalse((root / kind / "sess-1").exists())
                self.assertTrue(keep.is_file())
                self.assertFalse(scratch.purge_session_tmp("sess-missing"))

    def test_write_and_purge_inventory_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(scratch, "tmp_dir", return_value=Path(tmp)):
                report = {
                    "rawDir": "/footage/demo",
                    "masterBasename": "20260801-demo-master-v001",
                    "generatedAt": "2026-08-01T00:00:00Z",
                    "space": {
                        "preCleanupProjectBytes": 100,
                        "deleteCandidateBytes": 40,
                        "preservedBytes": 60,
                    },
                    "files": {
                        "scheduledForDeletion": [{"path": "edit/a.mp4", "bytes": 40}],
                        "preserved": [{"path": "edit/masters/a.mp4", "bytes": 60}],
                    },
                }
                report_path, meta_path = scratch.write_inventory_scratch(
                    "sess-1", report
                )
                self.assertTrue(report_path.is_file())
                self.assertTrue(meta_path.is_file())
                self.assertTrue(scratch.scratch_exists("sess-1"))
                self.assertTrue(scratch.purge_scratch("sess-1"))
                self.assertFalse(scratch.scratch_exists("sess-1"))


if __name__ == "__main__":
    unittest.main()
