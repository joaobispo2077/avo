"""Tests for helpers/avo_state.py atomic persistence."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AvoStateAtomicTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT))
        self._temp_dir = tempfile.mkdtemp()

    def test_save_state_atomic_writes_valid_json(self) -> None:
        from helpers import avo_state

        with mock.patch.object(avo_state, "repo_root") as repo_root:
            repo_root.return_value = Path(self._temp_dir)
            avo_state.save_state({"version": "1.0.0", "stats": {"a": 1}})
            path = avo_state.state_path()
            self.assertTrue(path.is_file())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["stats"]["a"], 1)

    def test_sessions_dir_creates_directory(self) -> None:
        from helpers import avo_state

        with mock.patch.object(avo_state, "repo_root") as repo_root:
            repo_root.return_value = Path(self._temp_dir)
            sessions = avo_state.sessions_dir()
            self.assertTrue(sessions.is_dir())
            self.assertEqual(sessions, Path(self._temp_dir) / ".avo" / "sessions")


if __name__ == "__main__":
    unittest.main()
