"""Voiceover mux command construction tests."""
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
FIXTURE = ROOT / "tests" / "fixtures" / "edl_voiceover_minimal.json"

from avo import render, voiceover


class VoiceoverMuxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self.tmp.name)
        edl = json.loads(FIXTURE.read_text(encoding="utf-8"))
        (self.edit / "clip_a.mp4").write_bytes(b"")
        (self.edit / "voiceover.wav").write_bytes(b"")
        (self.edit / "base.mp4").write_bytes(b"")
        self.edl_path = self.edit / "edl.json"
        self.edl_path.write_text(json.dumps(edl), encoding="utf-8")
        self.edl = json.loads(self.edl_path.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_extract_all_segments_video_only_for_voiceover(self) -> None:
        with mock.patch.object(render, "extract_segment") as extract:
            render.extract_all_segments(
                self.edl,
                self.edit,
                preview=False,
                draft=True,
            )
        self.assertTrue(extract.called)
        self.assertFalse(extract.call_args.kwargs["include_source_audio"])

    @mock.patch.object(render, "run_ffmpeg_progress")
    def test_mux_external_voiceover_ffmpeg_maps(self, progress: mock.Mock) -> None:
        out = self.edit / "out.mp4"
        render.mux_external_voiceover(
            self.edit / "base.mp4",
            self.edl,
            self.edit,
            out,
        )
        cmd = progress.call_args.args[0]
        self.assertIn("-filter:a:0", cmd)
        filter_idx = cmd.index("-filter:a:0") + 1
        self.assertIn("atrim=0:10.000", cmd[filter_idx])
        self.assertIn(str(self.edit / "voiceover.wav"), cmd)


if __name__ == "__main__":
    unittest.main()
