from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "helpers"))

import validate_edl


SCHEMA = ROOT / "specs/005-bluray-ps5-gamevlog/contracts/edl.schema.json"


def valid_edl(root: Path) -> dict:
    for name in ["DJI_20260506201325_0444_D.MP4", "overlay.webm", "sfx.wav", "captions.srt"]:
        (root / name).write_text("asset", encoding="utf-8")

    return {
        "version": 5,
        "feature_id": "005-bluray-ps5-gamevlog",
        "format_diagnosis_approval": "Gate 1 approved in EDITLOG.md",
        "story_map_approval": "Gate 1 approved in EDITLOG.md",
        "sources": {
            "main": {
                "path": str(root / "DJI_20260506201325_0444_D.MP4"),
                "role": "authoritative_master",
                "duration_seconds": 874.3735,
                "sha256": "0" * 64,
            },
            "overlay-1": {
                "path": "overlay.webm",
                "role": "approved_overlay",
                "duration_seconds": 3.0,
            },
            "sfx-1": {
                "path": "sfx.wav",
                "role": "approved_sfx",
                "duration_seconds": 0.4,
            },
        },
        "ranges": [
            {
                "source": "main",
                "start": 0.0,
                "end": 20.0,
                "story_section_id": "hook",
                "range_type": "main",
                "claim_ids": ["claim-001"],
            }
        ],
        "overlays": [
            {
                "file": "overlay.webm",
                "start_in_output": 2.0,
                "duration": 3.0,
                "motion_brief_id": "opening-orientation",
                "approval_reference": "ANIMATION-EDITLOG Gate 3 approved",
                "collision_qc_reference": "animations/qc/opening.md",
            }
        ],
        "sound_effects": [
            {
                "file": "sfx.wav",
                "start_in_output": 2.1,
                "duration": 0.4,
                "gain_db": -18.0,
                "purpose": "soft orientation cue below speech",
                "source_log_id": "sfx-001",
            }
        ],
        "audio": {
            "main_source_stream": "a:0",
            "output_channels": 2,
            "sample_rate_hz": 48000,
            "dialogue_mapping": "mono_centered_to_stereo",
            "noise_reduction_policy": "conservative_speech_first",
            "target_lufs": -16.0,
            "true_peak_limit_dbtp": -3.0,
            "treatment_plan_reference": "audio/audio-treatment-plan-v001.md",
        },
        "caption_policy": {
            "language": "pt-BR",
            "selectable": True,
            "visual_subtitles": False,
            "caption_path": "captions.srt",
            "correction_map_path": None,
        },
        "motion_policy": {
            "framework": "hyperframes",
            "density_levels": [1, 2],
            "timeline_owner": "edl",
            "review_package_approval": "ANIMATION-EDITLOG Gate 3 approved",
        },
        "grade": "bt709_sdr_light",
        "delivery": {
            "width": 3840,
            "height": 2160,
            "frame_rate": "30000/1001",
            "color_space": "bt709",
            "video_codec": "h264",
            "audio_codec": "aac",
            "fast_start": True,
        },
        "render_gate": {
            "stage": "fine",
            "approval_references": ["EDITLOG Gate 2 approved"],
        },
    }


class BlurayPs5EdlContractTests(unittest.TestCase):
    def test_valid_bluray_ps5_edl_passes_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            loaded = validate_edl.load_and_validate(path, schema_path=SCHEMA)
            self.assertEqual(loaded["feature_id"], "005-bluray-ps5-gamevlog")

    def test_proxy_lrf_cannot_be_used_as_finishing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            (root / "DJI_20260506201325_0444_D.LRF").write_text("proxy", encoding="utf-8")
            edl["sources"]["main"]["path"] = str(root / "DJI_20260506201325_0444_D.LRF")
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "LRF"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

    def test_final_ranges_must_resolve_to_authoritative_master(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            edl["ranges"][0]["source"] = "overlay-1"
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "authoritative_master"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

    def test_master_stage_requires_motion_and_multiple_release_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            edl["render_gate"] = {"stage": "master", "approval_references": ["picture lock"]}
            edl["motion_policy"]["review_package_approval"] = None
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "master render"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

    def test_overlay_and_sfx_asset_paths_must_exist_and_sfx_gain_negative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            bad = deepcopy(edl)
            bad["overlays"][0]["file"] = "missing.webm"
            path = root / "missing-overlay.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "overlays"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

            bad = deepcopy(edl)
            bad["sound_effects"][0]["gain_db"] = 0.0
            path = root / "bad-sfx.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "gain_db"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

    def test_overlay_window_must_stay_inside_output_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            edl["overlays"][0]["start_in_output"] = 19.0
            edl["overlays"][0]["duration"] = 3.0
            path = root / "bounds.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "beyond output"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)


if __name__ == "__main__":
    unittest.main()
