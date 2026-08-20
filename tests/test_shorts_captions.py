from __future__ import annotations

import unittest

from avo import shorts_captions

POLICY = {
    "grouping": {
        "maxWords": 3,
        "maxCharacters": 30,
        "maxDurationSec": 1.5,
        "maxGapSec": 0.42,
        "mergeOrphans": True,
    },
    "timing": {
        "minimumHoldSec": 0.18,
        "frameEpsilon": 1 / 30,
        "tailPadSec": 0.18,
        "autofixPolicy": "report-and-fix",
    },
    "highlight": {"mode": "moving-background", "resetAtPhraseBoundary": True},
}


class ShortsCaptionTests(unittest.TestCase):
    def test_maps_source_clock_and_normalizes_pt_br(self) -> None:
        words = [
            {"text": "R$", "start": 10, "end": 10.2},
            {"text": "1,000", "start": 10.2, "end": 10.6},
        ]
        mapped = shorts_captions.map_to_edited_time(
            words, source_start=10, source_end=12, speed=1.2, duration=2 / 1.2
        )
        self.assertAlmostEqual(mapped[1]["start"], 1 / 6)
        self.assertEqual(mapped[1]["text"], "1.000")

    def test_reviewed_replace_merge_split_and_omit_are_audited(self) -> None:
        words = [
            {"text": "Swith", "start": 0, "end": 0.2},
            {"text": "três", "start": 0.2, "end": 0.35},
            {"text": "mil", "start": 0.35, "end": 0.5},
            {"text": "hã", "start": 0.5, "end": 0.6},
        ]
        corrections = [
            {
                "operation": "replace",
                "match": ["Swith"],
                "replacement": ["Switch"],
                "reason": "produto",
                "approved": True,
            },
            {
                "operation": "merge",
                "match": ["três", "mil"],
                "replacement": ["3.000"],
                "reason": "número",
                "approved": True,
            },
            {
                "operation": "split",
                "match": ["Switch"],
                "replacement": ["Nintendo", "Switch"],
                "reason": "nome",
                "approved": True,
            },
            {
                "operation": "omit",
                "match": ["hã"],
                "reason": "fragmento abandonado",
                "approved": True,
            },
        ]
        corrected, audit = shorts_captions.apply_corrections(
            words, corrections, candidate_id="01"
        )
        self.assertEqual(
            [word["text"] for word in corrected], ["Nintendo", "Switch", "3.000"]
        )
        self.assertEqual(
            [entry["operation"] for entry in audit],
            ["replace", "merge", "split", "omit"],
        )

    def test_unapproved_correction_and_unreasoned_omission_fail(self) -> None:
        words = [{"text": "x", "start": 0, "end": 0.2}]
        with self.assertRaises(shorts_captions.CaptionError):
            shorts_captions.apply_corrections(
                words,
                [{"operation": "omit", "match": ["x"], "reason": "", "approved": True}],
                candidate_id="01",
            )

    def test_grouping_conserves_words_and_merges_orphan(self) -> None:
        words = [
            {"text": text, "start": index * 0.2, "end": index * 0.2 + 0.15}
            for index, text in enumerate(("um", "dois", "três", "quatro"))
        ]
        groups = shorts_captions.group_words(words, POLICY["grouping"])
        self.assertEqual(
            [word["text"] for group in groups for word in group],
            [word["text"] for word in words],
        )
        self.assertNotEqual(len(groups[-1]), 1)

    def test_last_content_word_punch_selection_marks_final_word(self) -> None:
        words = [
            {"text": "Switch", "start": 0, "end": 0.3},
            {"text": "vale", "start": 0.32, "end": 0.6},
            {"text": "a", "start": 0.62, "end": 0.7},
            {"text": "pena?", "start": 0.72, "end": 1.0},
        ]
        policy = {
            **POLICY,
            "highlight": {
                "mode": "moving-background",
                "resetAtPhraseBoundary": True,
                "punchSelection": "last-content-word",
            },
        }
        phrases = shorts_captions.build_phrases(words, policy, duration=1.1)
        self.assertTrue(phrases[0]["words"][-1]["punch"])

    def test_phrase_clamp_word_intervals_and_boundary_reset_are_seek_safe(self) -> None:
        words = [
            {"text": "OLED", "start": 0, "end": 0.38, "punch": True},
            {"text": "ou?", "start": 0.4, "end": 0.72},
            {"text": "Lite", "start": 0.74, "end": 1.0},
        ]
        policy = {**POLICY, "grouping": {**POLICY["grouping"], "mergeOrphans": False}}
        phrases = shorts_captions.build_phrases(words, policy, duration=1.1)
        self.assertGreaterEqual(len(phrases), 2)
        self.assertLessEqual(
            phrases[0]["endSec"], phrases[1]["startSec"] - 1 / 30 + 1e-6
        )
        for phrase in phrases:
            for word in phrase["words"]:
                self.assertLessEqual(word["highlightExitSec"], phrase["endSec"])
                self.assertGreaterEqual(
                    word["highlightExitSec"], word["highlightEnterSec"]
                )
        self.assertIsNone(shorts_captions.active_word_at(phrases, phrases[0]["endSec"]))
        self.assertEqual(shorts_captions.active_word_at(phrases, 0.1), "p1-w1")

    def test_anchor_rejects_seam_on_full_frame_and_protected_overlap(self) -> None:
        with self.assertRaises(shorts_captions.CaptionError):
            shorts_captions.validate_anchor("seam", layout_mode="full-frame")
        with self.assertRaises(shorts_captions.CaptionError):
            shorts_captions.validate_anchor(
                "top",
                layout_mode="full-frame",
                protected_regions=[{"x": 0, "y": 0, "width": 1, "height": 0.3}],
            )


if __name__ == "__main__":
    unittest.main()
