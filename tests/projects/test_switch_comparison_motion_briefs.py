from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    from jsonschema import Draft7Validator as Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "specs/003-switch-comparison-video/contracts/motion-brief.schema.json"
CATEGORIES = [
    "price",
    "value",
    "spec_compare",
    "physical_detail",
    "ergonomics",
    "portability",
    "performance",
    "library_compatibility",
    "recommendation",
    "evidence_callout",
    "summary",
    "ad_bridge",
]


def brief(category: str) -> dict:
    sfx_cue = "cash_register_money" if category in {"price", "value"} else "switch_ui_chime"
    return {
        "id": f"slot-{category.replace('_', '-')}",
        "revision_strategy": "rebuilt_v004",
        "category": category,
        "problem": "Viewer needs context without visual subtitles",
        "message": "Compare este ponto com clareza",
        "source_basis": {"type": "story_map", "reference": "story-map.md"},
        "output_window": {"start": 10.0, "duration": 2.5},
        "hold_policy": "extended_price_hold" if category in {"price", "value"} else "normal_readable",
        "safe_area": "center-safe",
        "visual_treatment": "quiet comparison card",
        "motion_lifecycle": "enter, hold, exit",
        "sfx_policy": "cash_themed_original" if category in {"price", "value"} else "switch_ui_inspired_original",
        "sfx_cue": sfx_cue,
        "sfx_gain_db": -20,
        "visual_subtitles": False,
        "text_qc": {
            "no_debug_text": True,
            "no_timing_readout": True,
            "no_ghost_category_label": True,
            "no_duplicate_hierarchy_text": True,
            "pt_br_reviewed": True,
        },
        "accessibility": {
            "readable": True,
            "no_flashing_risk": True,
            "does_not_cover_evidence": True,
        },
        "preview_evidence": {
            "composite_preview": "review/v004-animation-sfx-package/composite-previews/slot.mp4",
            "overlay_render": "animations_v004/slot/render/slot.mov",
            "snapshot": "animations_v004/slot/render/snapshot.png",
            "sfx_file": "animations_v004/slot/sfx/slot.wav",
        },
        "approval_status": "approved",
    }


class SwitchComparisonMotionBriefTests(unittest.TestCase):
    schema: dict

    @classmethod
    def setUpClass(cls) -> None:
        if not SCHEMA_PATH.is_file():
            raise unittest.SkipTest(
                f"missing local project spec (not in public repo): {SCHEMA_PATH}"
            )
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_supported_context_categories_validate(self) -> None:
        validator = Draft202012Validator(self.schema)
        for category in CATEGORIES:
            self.assertEqual([], list(validator.iter_errors(brief(category))), category)

    def test_visual_subtitles_are_rejected(self) -> None:
        item = brief("price")
        item["visual_subtitles"] = True
        errors = list(Draft202012Validator(self.schema).iter_errors(item))
        self.assertTrue(errors)

    def test_v004_revision_strategy_is_required(self) -> None:
        item = deepcopy(brief("value"))
        del item["revision_strategy"]
        errors = list(Draft202012Validator(self.schema).iter_errors(item))
        self.assertTrue(errors)

    def test_text_qc_is_required_and_strict(self) -> None:
        item = deepcopy(brief("summary"))
        item["text_qc"]["no_timing_readout"] = False
        errors = list(Draft202012Validator(self.schema).iter_errors(item))
        self.assertTrue(errors)

    def test_preview_evidence_is_required(self) -> None:
        item = deepcopy(brief("recommendation"))
        del item["preview_evidence"]
        errors = list(Draft202012Validator(self.schema).iter_errors(item))
        self.assertTrue(errors)

    def test_source_basis_is_required(self) -> None:
        item = deepcopy(brief("value"))
        del item["source_basis"]
        errors = list(Draft202012Validator(self.schema).iter_errors(item))
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
