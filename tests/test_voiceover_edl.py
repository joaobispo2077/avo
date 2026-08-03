"""Voiceover EDL validation tests."""
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

from avo import validate_edl, voiceover


class VoiceoverEdlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_valid_edl(self) -> Path:
        edl = json.loads(FIXTURE.read_text(encoding="utf-8"))
        (self.edit / "clip_a.mp4").write_bytes(b"")
        (self.edit / "voiceover.wav").write_bytes(b"")
        path = self.edit / "edl.json"
        path.write_text(json.dumps(edl), encoding="utf-8")
        return path

    def test_minimal_fixture_validates(self) -> None:
        path = self._write_valid_edl()
        loaded = validate_edl.load_and_validate(path)
        self.assertTrue(voiceover.is_external_voiceover_edl(loaded))
        self.assertEqual(voiceover.output_duration_from_edl(loaded), 10.0)

    def test_rejects_overlays_in_v1(self) -> None:
        path = self._write_valid_edl()
        edl = json.loads(path.read_text(encoding="utf-8"))
        edl["overlays"] = [{"file": "x.mov", "start_in_output": 0, "duration": 1}]
        path.write_text(json.dumps(edl), encoding="utf-8")
        with self.assertRaisesRegex(validate_edl.EdlValidationError, "overlays"):
            validate_edl.load_and_validate(path)

    def test_rejects_missing_voiceover_file(self) -> None:
        path = self._write_valid_edl()
        (self.edit / "voiceover.wav").unlink()
        with self.assertRaisesRegex(validate_edl.EdlValidationError, "voiceover source"):
            validate_edl.load_and_validate(path)

    def test_preflight_flags_short_voiceover(self) -> None:
        path = self._write_valid_edl()
        edl = validate_edl.load_and_validate(path)
        with mock.patch.object(voiceover, "media_duration", return_value=3.0):
            issues = voiceover.preflight(edl, self.edit)
        self.assertTrue(any("shorter than cut duration" in item for item in issues))


if __name__ == "__main__":
    unittest.main()
