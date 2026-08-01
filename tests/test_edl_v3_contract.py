from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import validate_edl


SLOT_IDS = [
    "transfer-direction",
    "move-not-copy-warning",
    "two-game-verification",
]
PURPOSES = ["transfer_whoosh", "warning_hit", "verification_chime"]


class EdlV3ContractTests(unittest.TestCase):
    def make_v3(self, edit: Path) -> dict:
        (edit / "master.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nTESTE\n", encoding="utf-8"
        )
        (edit / "caption-burn-in.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nTESTE\n", encoding="utf-8"
        )
        overlays = []
        effects = []
        for index, (slot_id, purpose) in enumerate(zip(SLOT_IDS, PURPOSES)):
            overlay = edit / f"{slot_id}.mov"
            sfx = edit / f"{slot_id}.wav"
            overlay.touch()
            sfx.touch()
            overlays.append(
                {
                    "file": overlay.name,
                    "start_in_output": 2.0 + index * 3.0,
                    "duration": 1.0,
                    "motion_brief_id": slot_id,
                }
            )
            effects.append(
                {
                    "file": sfx.name,
                    "start_in_output": 2.0 + index * 3.0,
                    "duration": 0.5,
                    "gain_db": -12.0,
                    "motion_brief_id": slot_id,
                    "purpose": purpose,
                }
            )
        return {
            "version": 3,
            "story_map_approval": "approved",
            "sources": {"clip": "clip.mp4"},
            "ranges": [
                {
                    "source": "clip",
                    "start": 0.0,
                    "end": 20.0,
                    "story_section_id": "s1",
                }
            ],
            "grade": "subtle",
            "overlays": overlays,
            "sound_effects": effects,
            "audio": {
                "source_stream": "a:0",
                "output_channels": 2,
                "sample_rate_hz": 48000,
                "preset": "speech_stereo",
                "target_lufs": -16,
                "true_peak_limit_dbtp": -1,
            },
            "subtitles": "master.srt",
            "caption_burn_in": {
                "file": "caption-burn-in.srt",
                "start_in_output": 0,
                "end_in_output": 60,
                "alignment": "seam_center",
                "center_y_ratio": 0.5,
                "strip_terminal_periods": True,
                "render_order": "after_overlays",
            },
        }

    def test_historical_v2_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edl.json"
            edl = {
                "version": 2,
                "story_map_approval": "approved",
                "sources": {"clip": "clip.mp4"},
                "ranges": [
                    {
                        "source": "clip",
                        "start": 0,
                        "end": 1,
                        "story_section_id": "s1",
                    }
                ],
                "grade": None,
                "overlays": [],
                "subtitles": None,
            }
            path.write_text(json.dumps(edl), encoding="utf-8")
            self.assertEqual(validate_edl.load_and_validate(path), edl)

    def test_valid_v3_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            edit = Path(tmp)
            path = edit / "edl.json"
            edl = self.make_v3(edit)
            path.write_text(json.dumps(edl), encoding="utf-8")
            self.assertEqual(validate_edl.load_and_validate(path), edl)

    def test_duplicate_slot_and_missing_asset_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            edit = Path(tmp)
            path = edit / "edl.json"
            edl = self.make_v3(edit)
            edl["overlays"][2]["motion_brief_id"] = SLOT_IDS[0]
            Path(edit / edl["sound_effects"][1]["file"]).unlink()
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaises(validate_edl.EdlValidationError) as raised:
                validate_edl.load_and_validate(path)
            message = str(raised.exception)
            self.assertIn("exactly once", message)
            self.assertIn("does not exist", message)

    def test_overlap_and_out_of_bounds_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            edit = Path(tmp)
            path = edit / "edl.json"
            edl = self.make_v3(edit)
            edl["overlays"][1]["start_in_output"] = 2.5
            edl["sound_effects"][2]["start_in_output"] = 19.8
            edl["sound_effects"][2]["duration"] = 1.0
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaises(validate_edl.EdlValidationError) as raised:
                validate_edl.load_and_validate(path)
            self.assertIn("overlap", str(raised.exception))
            self.assertIn("output duration", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

