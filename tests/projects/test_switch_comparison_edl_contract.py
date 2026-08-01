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


SCHEMA = ROOT / "specs/003-switch-comparison-video/contracts/edl.schema.json"


def valid_edl(root: Path) -> dict:
    for name in ["a.mp4", "b.mp4", "ad.mp4", "master.srt"]:
        (root / name).write_text("asset", encoding="utf-8")
    for index in range(6):
        (root / f"overlay-{index}.mov").write_text("overlay", encoding="utf-8")
    for index in range(2):
        (root / f"sfx-{index}.wav").write_text("sfx", encoding="utf-8")

    categories = [
        "price",
        "value",
        "spec_compare",
        "physical_detail",
        "library_compatibility",
        "summary",
    ]
    overlays = [
        {
            "file": f"overlay-{index}.mov",
            "start_in_output": index * 3.0,
            "duration": 1.0,
            "motion_brief_id": f"slot-{index}",
            "category": category,
            "safe_area": "center-safe",
        }
        for index, category in enumerate(categories)
    ]

    return {
        "version": 4,
        "story_map_approval": "Gate 1 approved",
        "sources": {
            "main-a": str(root / "a.mp4"),
            "main-b": str(root / "b.mp4"),
            "ad": str(root / "ad.mp4"),
        },
        "blocked_source_ranges": [
            {
                "source": "main-a",
                "inspection_start": 960.0,
                "inspection_end": 1020.0,
                "minimum_excluded_start": 967.0,
                "minimum_excluded_end": 978.0,
                "final_cut_start": 966.7,
                "final_cut_end": 979.2,
                "reason": "belly_camera_repeated_phrase",
                "qc_status": "pending",
            }
        ],
        "ranges": [
            {
                "source": "main-a",
                "start": 0.0,
                "end": 12.0,
                "story_section_id": "opening",
                "range_type": "main_comparison",
            },
            {
                "source": "ad",
                "start": 0.0,
                "end": 6.0,
                "story_section_id": "ad",
                "range_type": "ad_segment",
            },
        ],
        "ad_segment": {
            "approved_asset": "ad.mp4",
            "insertion_policy": "midpoint_natural_break",
            "approval_status": "approved",
        },
        "audio": {
            "main_source_stream": "a:0",
            "output_channels": 2,
            "sample_rate_hz": 48000,
            "preset": "speech_stereo_with_ad_match",
            "target_lufs": -16,
            "true_peak_limit_dbtp": -3,
            "ad_audio_policy": "select_cleanest_stereo_track",
            "noise_reduction_policy": "conservative_speech_first",
            "channel_qc": "passed_left_right_dialogue_audible",
        },
        "caption_policy": {
            "selectable_captions": True,
            "visual_subtitles": False,
            "language": "pt-BR",
            "final_master_transcript_required": True,
        },
        "motion_policy": {
            "density_level": 3,
            "purpose": "comparison_contexts",
            "visual_subtitles_allowed": False,
            "minimum_approved_overlays": 6,
            "approval_status": "approved",
            "rebuild_scope": "rebuilt_v004_hyperframes",
            "review_package_required": True,
        },
        "render_gate": {
            "stage": "full_render_after_creator_approval",
            "full_render_allowed": True,
            "creator_approval_reference": "EDITLOG Gate 4 approved",
        },
        "review_package": {
            "manifest": "review/v004-animation-sfx-package/package-manifest.md",
            "composite_preview_dir": "review/v004-animation-sfx-package/composite-previews",
            "overlay_render_dir": "review/v004-animation-sfx-package/overlay-renders",
            "sfx_dir": "review/v004-animation-sfx-package/sfx",
            "approval_status": "approved",
        },
        "subtitles": "master.srt",
        "caption_burn_in": None,
        "overlays": overlays,
        "sound_effects": [
            {
                "file": "sfx-0.wav",
                "start_in_output": 0.25,
                "duration": 0.4,
                "gain_db": -18,
                "motion_brief_id": "slot-0",
                "purpose": "cash_register_money",
            },
            {
                "file": "sfx-1.wav",
                "start_in_output": 15.0,
                "duration": 0.3,
                "gain_db": -20,
                "motion_brief_id": "slot-5",
                "purpose": "verification_chime",
            },
        ],
        "delivery": {
            "resolution": "3840x2160",
            "frame_rate_policy": "match_main_2997",
            "container": "mp4",
            "video_codec": "h264_high",
            "audio_codec": "aac_lc",
            "audio_sample_rate_hz": 48000,
            "audio_channels": 2,
        },
    }


class SwitchComparisonEdlContractTests(unittest.TestCase):
    def test_valid_comparison_edl_allows_many_overlays_optional_sfx_no_burn_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            loaded = validate_edl.load_and_validate(path, schema_path=SCHEMA)
            self.assertEqual(len(loaded["overlays"]), 6)

    def test_v004_review_package_gate_blocks_full_render_without_creator_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            edl["render_gate"] = {
                "stage": "v004_review_package",
                "full_render_allowed": False,
                "creator_approval_reference": None,
            }
            edl["motion_policy"]["approval_status"] = "draft"
            edl["review_package"]["approval_status"] = "draft"
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            loaded = validate_edl.load_and_validate(path, schema_path=SCHEMA)
            self.assertFalse(loaded["render_gate"]["full_render_allowed"])

    def test_full_render_requires_approved_review_package_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            edl["render_gate"] = {
                "stage": "full_render_after_creator_approval",
                "full_render_allowed": True,
                "creator_approval_reference": None,
            }
            edl["review_package"]["approval_status"] = "draft"
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "review package approval"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

    def test_blocked_source_range_must_cover_minimum_belly_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            edl["blocked_source_ranges"][0]["final_cut_start"] = 970.0
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "minimum excluded"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

    def test_visual_subtitle_asset_is_rejected_for_comparison_edl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            edl["caption_burn_in"] = {"file": "burn.srt", "end_in_output": 60}
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaises(validate_edl.EdlValidationError):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

    def test_sfx_must_reference_existing_overlay_but_overlay_sfx_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            edl["sound_effects"][0]["motion_brief_id"] = "missing-slot"
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "matching overlay"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

    def test_duplicate_or_out_of_bounds_overlay_fails_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            bad = deepcopy(edl)
            bad["overlays"][1]["motion_brief_id"] = bad["overlays"][0]["motion_brief_id"]
            path = root / "duplicate.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "duplicate overlay"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

            bad = deepcopy(edl)
            bad["overlays"][0]["start_in_output"] = 99.0
            path = root / "bounds.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "beyond output"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)

    def test_missing_approved_ad_asset_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edl = valid_edl(root)
            edl["ad_segment"]["approved_asset"] = "missing-ad.mp4"
            path = root / "edl.json"
            path.write_text(json.dumps(edl), encoding="utf-8")
            with self.assertRaisesRegex(validate_edl.EdlValidationError, "approved_asset"):
                validate_edl.load_and_validate(path, schema_path=SCHEMA)


if __name__ == "__main__":
    unittest.main()
