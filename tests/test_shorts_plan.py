"""Pure resolver tests for the Shorts planning MVP."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from avo import shorts_contract, shorts_plan

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "shorts" / "planning"


def load_request() -> dict:
    return json.loads((FIXTURE_DIR / "shorts.request.json").read_text(encoding="utf-8"))


def load_transcript() -> dict:
    return json.loads((FIXTURE_DIR / "transcript.json").read_text(encoding="utf-8"))


class ShortsPlanTests(unittest.TestCase):
    def test_exact_count_order_duration_defaults_and_hash_are_deterministic(
        self,
    ) -> None:
        request = load_request()
        first = shorts_plan.resolve_batch(
            request,
            load_transcript(),
            request_path=FIXTURE_DIR / "shorts.request.json",
        )
        second = shorts_plan.resolve_batch(
            deepcopy(request),
            load_transcript(),
            request_path=FIXTURE_DIR / "shorts.request.json",
        )
        self.assertEqual(first["resolvedCount"], 10)
        self.assertEqual(
            [item["id"] for item in first["items"]], [f"{i:02d}" for i in range(1, 11)]
        )
        self.assertAlmostEqual(
            first["items"][0]["editedDurationSec"], 5 / 1.2, places=6
        )
        self.assertEqual(first["items"][1]["layout"]["captionAnchor"], "bottom")
        self.assertEqual(first["planHash"], second["planHash"])
        self.assertEqual(shorts_contract.plan_hash(first), first["planHash"])

    def test_speed_bounds_and_max_duration_are_enforced(self) -> None:
        request = load_request()
        request["candidates"][0]["requestedSpeed"] = 1.3
        with self.assertRaises(shorts_plan.PlanningError) as raised:
            shorts_plan.resolve_batch(
                request,
                load_transcript(),
                request_path=FIXTURE_DIR / "shorts.request.json",
            )
        self.assertIn("speed", str(raised.exception))

        request = load_request()
        request["output"]["maxDurationSec"] = 3
        with self.assertRaises(shorts_plan.PlanningError) as raised:
            shorts_plan.resolve_batch(
                request,
                load_transcript(),
                request_path=FIXTURE_DIR / "shorts.request.json",
            )
        self.assertIn("maxDurationSec", str(raised.exception))

    def test_duplicate_angle_and_range_without_words_are_rejected(self) -> None:
        request = load_request()
        request["candidates"][1]["viewerPromise"] = request["candidates"][0][
            "viewerPromise"
        ]
        request["candidates"][1]["sourceRange"] = deepcopy(
            request["candidates"][0]["sourceRange"]
        )
        with self.assertRaises(shorts_plan.PlanningError) as raised:
            shorts_plan.resolve_batch(
                request,
                load_transcript(),
                request_path=FIXTURE_DIR / "shorts.request.json",
            )
        self.assertIn("duplicate", str(raised.exception))

        request = load_request()
        request["candidates"][-1]["sourceRange"] = {"startSec": 96, "endSec": 99}
        with self.assertRaises(shorts_plan.PlanningError) as raised:
            shorts_plan.resolve_batch(
                request,
                load_transcript(),
                request_path=FIXTURE_DIR / "shorts.request.json",
            )
        self.assertIn("transcript words", str(raised.exception))

    def test_source_evidence_must_be_present_in_candidate_words(self) -> None:
        request = load_request()
        request["candidates"][2]["sourceEvidence"] = "evidência inexistente"
        with self.assertRaises(shorts_plan.PlanningError) as raised:
            shorts_plan.resolve_batch(
                request,
                load_transcript(),
                request_path=FIXTURE_DIR / "shorts.request.json",
            )
        self.assertIn("sourceEvidence", str(raised.exception))

    def test_plan_starts_pending_and_records_intelligibility_review(self) -> None:
        plan = shorts_plan.resolve_batch(
            load_request(),
            load_transcript(),
            request_path=FIXTURE_DIR / "shorts.request.json",
        )
        self.assertEqual(plan["planApproval"]["status"], "pending")
        self.assertTrue(
            any("01" in finding for finding in plan["requiredHumanReviews"])
        )
        self.assertIn("review://01", plan["items"][0]["factualReviewReferences"])
        with self.assertRaises(shorts_contract.ContractValidationError):
            shorts_contract.require_plan_approval(plan)

    def test_reviewed_corrections_are_request_data_and_change_plan_identity(
        self,
    ) -> None:
        request = load_request()
        first = shorts_plan.resolve_batch(
            request,
            load_transcript(),
            request_path=FIXTURE_DIR / "shorts.request.json",
        )
        request["corrections"][0]["replacement"] = ["ideia", "3"]
        second = shorts_plan.resolve_batch(
            request,
            load_transcript(),
            request_path=FIXTURE_DIR / "shorts.request.json",
        )
        self.assertNotEqual(first["requestHash"], second["requestHash"])
        self.assertNotEqual(first["planHash"], second["planHash"])

    def test_percentage_allocation_of_ten_is_exactly_three_and_explicit(self) -> None:
        request = load_request()
        request["insertions"] = [
            {
                "id": "gameplay",
                "sourcePath": "gameplay.mkv",
                "videoStream": "0:v:0",
                "audioStream": "0:a:0",
                "approvedWindows": [{"startSec": 5, "endSec": 46.5}],
                "excludedWindows": [],
                "repeatMode": "finite-repeat",
                "supportVolume": 0.2,
                "layoutRole": "secondary-pane",
                "rightsBasis": "owned gameplay",
                "semanticApprovalReference": "watch://gameplay",
                "allocation": {
                    "mode": "percentage",
                    "percentage": 30,
                    "roundingRule": "nearest",
                    "selectionRule": "ordered",
                },
            }
        ]
        plan = shorts_plan.resolve_batch(
            request, load_transcript(), request_path=FIXTURE_DIR / "shorts.request.json"
        )
        self.assertEqual(
            [row["candidateId"] for row in plan["insertionAllocation"]],
            ["01", "02", "03"],
        )
        self.assertEqual(plan["items"][0]["insertion"]["audioStreamIndex"], "0:a:0")

    def test_lowest_visual_interest_allocation_selects_lowest_scores(self) -> None:
        request = load_request()
        for index, candidate in enumerate(request["candidates"]):
            candidate["visualInterestScore"] = 100 - index
        request["insertions"] = [
            {
                "id": "gameplay",
                "sourcePath": "gameplay.mkv",
                "videoStream": "0:v:0",
                "audioStream": "0:a:0",
                "approvedWindows": [{"startSec": 5, "endSec": 46.5}],
                "excludedWindows": [],
                "repeatMode": "finite-repeat",
                "supportVolume": 0.2,
                "layoutRole": "secondary-pane",
                "rightsBasis": "owned gameplay",
                "semanticApprovalReference": "watch://gameplay",
                "allocation": {
                    "mode": "percentage",
                    "percentage": 30,
                    "roundingRule": "nearest",
                    "selectionRule": "lowest-visual-interest",
                },
            }
        ]
        plan = shorts_plan.resolve_batch(
            request, load_transcript(), request_path=FIXTURE_DIR / "shorts.request.json"
        )
        self.assertEqual(
            [row["candidateId"] for row in plan["insertionAllocation"]],
            ["10", "09", "08"],
        )

    def test_missing_provider_tokens_adds_warning(self) -> None:
        request = load_request()
        request["provider"] = "provider-missing-for-test"
        plan = shorts_plan.resolve_batch(
            request,
            load_transcript(),
            request_path=FIXTURE_DIR / "shorts.request.json",
        )
        self.assertTrue(
            any("design tokens" in warning for warning in plan.get("warnings") or [])
        )


if __name__ == "__main__":
    unittest.main()
