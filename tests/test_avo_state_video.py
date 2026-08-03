"""Tests for per-video state and active context."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from avo import avo_state


class VideoStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name) / ".avo"
        self.state_dir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @mock.patch.object(avo_state, "state_dir")
    def test_video_state_key(self, mock_dir: mock.MagicMock) -> None:
        mock_dir.return_value = self.state_dir
        self.assertEqual(avo_state.video_state_key("bishop", "demo-one"), "bishop:demo-one")

    @mock.patch.object(avo_state, "state_dir")
    @mock.patch.object(avo_state, "state_path")
    def test_set_and_get_video_state(self, mock_path: mock.MagicMock, mock_dir: mock.MagicMock) -> None:
        mock_dir.return_value = self.state_dir
        state_file = self.state_dir / "state.json"
        mock_path.return_value = state_file

        state = avo_state.default_state()
        avo_state.set_video_state(state, "bishop:demo", {"transcription": {"model": "small"}})
        slice_ = avo_state.get_video_state(state, "bishop:demo")
        self.assertEqual(slice_["transcription"]["model"], "small")

    @mock.patch.object(avo_state, "state_dir")
    def test_active_context_roundtrip(self, mock_dir: mock.MagicMock) -> None:
        mock_dir.return_value = self.state_dir
        avo_state.save_active_context(
            {
                "mode": "concurrency",
                "provider": "bishop",
                "videoId": "demo",
                "rawDir": "H:/footage/demo",
            }
        )
        active = avo_state.load_active_context()
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active["provider"], "bishop")
        self.assertEqual(active["videoId"], "demo")
        avo_state.clear_active_context()
        self.assertIsNone(avo_state.load_active_context())


if __name__ == "__main__":
    unittest.main()
