"""Pure resolver tests for the Shorts planning MVP."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from avo import shorts_contract, shorts_plan

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "shorts" / "planning"
V11_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "shorts" / "planning-v11"


def load_request() -> dict:
    return json.loads((FIXTURE_DIR / "shorts.request.json").read_text(encoding="utf-8"))


def load_transcript() -> dict:
    return json.loads((FIXTURE_DIR / "transcript.json").read_text(encoding="utf-8"))


def load_v11_fixture(name: str) -> dict:
    return json.loads((V11_FIXTURE_DIR / name).read_text(encoding="utf-8"))


class ShortsPlanTests(unittest.TestCase):
    def test_v11_fixture_preserves_exact_order_without_enclosing_range(self) -> None:
        request = load_v11_fixture("shorts.request.json")
        transcript = load_v11_fixture("transcript.json")
        media = load_v11_fixture("media.json")
        cases = load_v11_fixture("cases.json")
        self.assertEqual(request["candidates"][0]["sourceSegments"], cases["reordered"])
        plan = shorts_plan.resolve_batch(
            request,
            transcript,
            request_path=V11_FIXTURE_DIR / "shorts.request.json",
            source_fingerprint=media["mediaFingerprint"],
            provider_tokens={},
        )
        item = plan["items"][0]
        self.assertNotIn("sourceRange", item)
        self.assertEqual(
            [(row["startSec"], row["endSec"]) for row in item["sourceSegments"]],
            [(10.0, 12.0), (30.0, 32.0), (20.0, 22.0)],
        )
        self.assertEqual(
            [row["outputStartSec"] for row in item["sourceSegments"]],
            [0.0, 2.0, 4.0],
        )
        self.assertEqual(item["editedDurationSec"], 6.0)
        self.assertEqual(
            [word["text"] for phrase in item["captions"] for word in phrase["words"]],
            ["first", "second", "third"],
        )
        self.assertEqual(shorts_contract.plan_hash(plan), plan["planHash"])

    def test_v11_fixture_approved_overlap_and_changed_fingerprint(self) -> None:
        request = load_v11_fixture("shorts.request.json")
        transcript = load_v11_fixture("transcript.json")
        media = load_v11_fixture("media.json")
        cases = load_v11_fixture("cases.json")
        request["source"]["expectedFingerprint"] = media["mediaFingerprint"]
        candidate = request["candidates"][0]
        candidate["sourceSegments"] = cases["overlappingApproved"]
        candidate["sourceEvidence"] = "first"
        plan = shorts_plan.resolve_batch(
            request,
            transcript,
            request_path=V11_FIXTURE_DIR / "shorts.request.json",
            source_fingerprint=media["mediaFingerprint"],
            provider_tokens={},
        )
        self.assertEqual(
            plan["items"][0]["sourceSegments"][1]["overlapApprovalReference"],
            "approval://repeat",
        )
        with self.assertRaisesRegex(shorts_plan.PlanningError, "fingerprint"):
            shorts_plan.resolve_batch(
                request,
                transcript,
                request_path=V11_FIXTURE_DIR / "shorts.request.json",
                source_fingerprint=media["changedMediaFingerprint"],
                provider_tokens={},
            )

    def test_v11_fixture_invalid_overlap_and_zero_duration_fail(self) -> None:
        for case in ("invalidOverlap", "zeroDuration"):
            request = load_v11_fixture("shorts.request.json")
            request["candidates"][0]["sourceSegments"] = load_v11_fixture("cases.json")[
                case
            ]
            with (
                self.subTest(case=case),
                self.assertRaises(shorts_contract.ContractValidationError),
            ):
                shorts_plan.resolve_batch(
                    request,
                    load_v11_fixture("transcript.json"),
                    request_path=V11_FIXTURE_DIR / "shorts.request.json",
                    source_fingerprint="a" * 64,
                    provider_tokens={},
                )

    def test_v11_preserves_declared_segment_order_and_output_mapping(self) -> None:
        request = load_request()
        request["version"] = "1.1"
        request["batchRoot"] = str(FIXTURE_DIR / "batch")
        request["batchRootSource"] = "canonical-default"
        request["source"].update({"sourceId": "master", "durationSec": 100})
        request["candidates"] = [request["candidates"][0]]
        request["requestedCount"] = 1
        candidate = request["candidates"][0]
        candidate.pop("sourceRange")
        candidate["sourceEvidence"] = "ideia dois"
        candidate["sourceSegments"] = [
            {
                "order": 1,
                "sourceId": "master",
                "startSec": 10,
                "endSec": 15,
                "rationale": "payoff",
                "evidenceReference": "review://2",
            },
            {
                "order": 2,
                "sourceId": "master",
                "startSec": 0,
                "endSec": 5,
                "rationale": "context",
                "evidenceReference": "review://1",
            },
        ]
        plan = shorts_plan.resolve_batch(
            request,
            load_transcript(),
            request_path=FIXTURE_DIR / "shorts.request-v11.json",
            source_fingerprint="a" * 64,
            provider_tokens={},
        )
        segments = plan["items"][0]["sourceSegments"]
        self.assertEqual([row["startSec"] for row in segments], [10.0, 0.0])
        self.assertEqual(segments[0]["outputStartSec"], 0)
        self.assertEqual(segments[1]["outputStartSec"], segments[0]["outputEndSec"])
        words = [
            word["text"]
            for phrase in plan["items"][0]["captions"]
            for word in phrase["words"]
        ]
        self.assertEqual(words[:2], ["ideia dois", "ideia um"])
        self.assertEqual(
            len(
                {
                    word["id"]
                    for phrase in plan["items"][0]["captions"]
                    for word in phrase["words"]
                }
            ),
            len(words),
        )

    def test_v11_rejects_unapproved_overlap_zero_duration_bounds_and_changed_fingerprint(
        self,
    ) -> None:
        request = load_request()
        request["version"] = "1.1"
        request["batchRoot"] = str(FIXTURE_DIR / "batch")
        request["batchRootSource"] = "canonical-default"
        request["source"].update(
            {"sourceId": "master", "durationSec": 100, "expectedFingerprint": "a" * 64}
        )
        request["candidates"] = [request["candidates"][0]]
        request["requestedCount"] = 1
        candidate = request["candidates"][0]
        candidate.pop("sourceRange")
        base = {
            "sourceId": "master",
            "rationale": "reason",
            "evidenceReference": "review://evidence",
        }
        for segments, message in (
            (
                [
                    {**base, "order": 1, "startSec": 1, "endSec": 4},
                    {**base, "order": 2, "startSec": 3, "endSec": 5},
                ],
                "overlap",
            ),
            ([{**base, "order": 1, "startSec": 4, "endSec": 4}], "endSec"),
            ([{**base, "order": 1, "startSec": 99, "endSec": 101}], "duration"),
        ):
            candidate["sourceSegments"] = segments
            with (
                self.subTest(message=message),
                self.assertRaises(shorts_contract.ContractValidationError),
            ):
                shorts_plan.resolve_batch(
                    request,
                    load_transcript(),
                    request_path="request.json",
                    source_fingerprint="a" * 64,
                    provider_tokens={},
                )
        candidate["sourceSegments"] = [{**base, "order": 1, "startSec": 0, "endSec": 5}]
        with self.assertRaisesRegex(shorts_plan.PlanningError, "fingerprint"):
            shorts_plan.resolve_batch(
                request,
                load_transcript(),
                request_path="request.json",
                source_fingerprint="b" * 64,
                provider_tokens={},
            )

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
