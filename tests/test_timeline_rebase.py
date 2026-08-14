from __future__ import annotations

import unittest

from avo.timeline.lineage import propose_bmap_rebase
from avo.timeline.mapping import classify_cue_rebase


def cue(cue_id: str) -> dict:
    return {
        "cueId": cue_id,
        "start": {"ticks": 100, "timebase": {"num": 1, "den": 1000}, "domain": "cmap-output"},
        "end": {"ticks": 200, "timebase": {"num": 1, "den": 1000}, "domain": "cmap-output"},
        "reviewState": "pending",
    }


class RebaseTests(unittest.TestCase):
    def test_classes(self):
        cases = [
            ("preserved", [(100, 200)], [(100, 200)]),
            ("shifted", [(100, 200)], [(200, 300)]),
            ("split", [(100, 300)], [(100, 150), (200, 300)]),
            ("removed", [(100, 200)], []),
        ]
        for expected, old, new in cases:
            with self.subTest(expected):
                self.assertEqual(classify_cue_rebase(old, new), expected)

    def test_ambiguous(self):
        self.assertEqual(
            classify_cue_rebase([(100, 200)], [(100, 200), (300, 400)]),
            "ambiguous",
        )

    def test_unsupported(self):
        self.assertEqual(classify_cue_rebase([], [(1, 2)]), "unsupported")

    def test_proposal_accounts_for_every_cue_and_only_moves_safe_outcomes(self):
        cues = [cue(name) for name in ("preserved", "shifted", "split", "removed", "ambiguous", "unsupported")]
        for item in cues:
            item["rawAnchorRanges"] = [] if item["cueId"] == "unsupported" else [[100, 200]]
        mapped = {
            "preserved": [[100, 200]],
            "shifted": [[200, 300]],
            "split": [[100, 140], [160, 200]],
            "removed": [],
            "ambiguous": [[100, 200], [300, 400]],
            "unsupported": [[1, 2]],
        }
        report = propose_bmap_rebase(cues, mapped)
        self.assertEqual(
            {item["cueId"]: item["outcome"] for item in report["outcomes"]},
            {
                "preserved": "preserved",
                "shifted": "shifted",
                "split": "split",
                "removed": "removed",
                "ambiguous": "ambiguous",
                "unsupported": "unsupported",
            },
        )
        proposed = {item["cueId"]: item for item in report["proposedCues"]}
        self.assertEqual(proposed["shifted"]["start"]["ticks"], 200)
        self.assertEqual(
            {item["cueId"] for item in report["blockers"]},
            {"split", "removed", "ambiguous", "unsupported"},
        )
