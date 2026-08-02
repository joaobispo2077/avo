"""Tests for src/avo/scratch.py and learndown scratch lifecycle."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from avo import scratch  # noqa: E402


class ScratchTests(unittest.TestCase):
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
                report_path, meta_path = scratch.write_inventory_scratch("sess-1", report)
                self.assertTrue(report_path.is_file())
                self.assertTrue(meta_path.is_file())
                self.assertTrue(scratch.scratch_exists("sess-1"))
                self.assertTrue(scratch.purge_scratch("sess-1"))
                self.assertFalse(scratch.scratch_exists("sess-1"))


if __name__ == "__main__":
    unittest.main()
