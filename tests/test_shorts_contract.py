"""Contract and state invariants for the reusable Shorts batch workflow."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from avo import shorts_contract


HASH = "a" * 64


def valid_request() -> dict:
    return {
        "version": "1.0",
        "batchId": "demo-batch",
        "provider": "bishop",
        "source": {"masterPath": "/media/master.mp4"},
        "destination": "youtube-shorts",
        "language": "pt-BR",
        "requestedCount": 1,
        "output": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "maxDurationSec": 60,
        },
        "defaults": {
            "speed": {
                "default": 1.0,
                "minimum": 1.0,
                "maximum": 1.2,
                "preservePitch": True,
            },
            "layout": {"mode": "full-frame", "captionAnchor": "bottom"},
            "captions": {
                "identity": "anchor-rail",
                "continuousDuringSpeech": True,
                "anchor": "bottom",
                "grouping": {
                    "maxWords": 4,
                    "maxCharacters": 32,
                    "maxDurationSec": 1.35,
                    "maxGapSec": 0.42,
                },
                "timing": {
                    "minimumHoldSec": 0.18,
                    "frameEpsilon": 0.033333,
                    "tailPadSec": 0.18,
                    "autofixPolicy": "report-and-fix",
                },
                "highlight": {
                    "mode": "moving-background",
                    "resetAtPhraseBoundary": True,
                },
            },
        },
        "candidates": [
            {
                "id": "01",
                "order": 1,
                "coreIdea": "One clear idea",
                "viewerPromise": "The viewer gets one answer",
                "postingTitle": "One answer",
                "sourceEvidence": "Evidence from the transcript",
                "sourceRange": {"startSec": 1.0, "endSec": 11.0},
                "editorialApprovalReference": "review://candidate-01",
            }
        ],
        "approvalGates": ["batch-plan", "motion-proof", "picture-lock", "rights", "pre-master"],
    }


def valid_plan() -> dict:
    item = {
        "id": "01",
        "order": 1,
        "coreIdea": "One clear idea",
        "viewerPromise": "The viewer gets one answer",
        "postingTitle": "One answer",
        "sourceRange": {"startSec": 1.0, "endSec": 11.0},
        "sourceEvidence": "Evidence from the transcript",
        "speed": 1.0,
        "editedDurationSec": 10.0,
        "layout": {"mode": "full-frame", "captionAnchor": "bottom"},
        "captions": [],
        "inputFingerprint": HASH,
        "expectedOutputBasename": "demo-short-01",
        "qcProfile": "shorts-proof",
    }
    plan = {
        "version": "1.0",
        "batchId": "demo-batch",
        "planRevision": 1,
        "requestPath": "shorts.request.json",
        "requestHash": HASH,
        "requestedCount": 1,
        "resolvedCount": 1,
        "output": {},
        "items": [item],
        "insertionAllocation": [],
        "planApproval": {"status": "approved", "reference": "review://plan"},
        "planHash": "0" * 64,
    }
    plan["planHash"] = shorts_contract.plan_hash(plan)
    return plan


def valid_status(plan: dict) -> dict:
    return {
        "version": "1.0",
        "batchId": plan["batchId"],
        "planPath": "plans/shorts.plan-v001.json",
        "planHash": plan["planHash"],
        "batchState": "plan-approved",
        "updatedAt": "2026-08-12T00:00:00Z",
        "items": [
            {
                "shortId": "01",
                "inputFingerprint": HASH,
                "state": "pending",
                "dirty": False,
                "proofRevision": 0,
                "masterRevision": 0,
                "artifacts": [],
                "errors": [],
            }
        ],
    }


class ShortsSchemaTests(unittest.TestCase):
    def test_runtime_schemas_are_valid_draft_2020_12(self) -> None:
        for kind in ("request", "plan", "status", "composition"):
            Draft202012Validator.check_schema(shorts_contract.load_schema(kind))

    def test_valid_request_plan_and_status_pass(self) -> None:
        request = valid_request()
        plan = valid_plan()
        status = valid_status(plan)
        self.assertEqual(shorts_contract.validate_document(request, "request"), request)
        self.assertEqual(shorts_contract.validate_document(plan, "plan"), plan)
        self.assertEqual(shorts_contract.validate_document(status, "status"), status)
        shorts_contract.ensure_plan_status_match(plan, status)

    def test_schema_errors_include_actionable_path(self) -> None:
        request = valid_request()
        request["output"]["width"] = 0
        with self.assertRaises(shorts_contract.ContractValidationError) as raised:
            shorts_contract.validate_document(request, "request")
        self.assertIn("output.width", str(raised.exception))


class ShortsInvariantTests(unittest.TestCase):
    def test_canonical_hash_ignores_mapping_order(self) -> None:
        left = {"b": 2, "a": {"d": 4, "c": 3}}
        right = {"a": {"c": 3, "d": 4}, "b": 2}
        self.assertEqual(shorts_contract.canonical_json(left), shorts_contract.canonical_json(right))
        self.assertEqual(shorts_contract.content_hash(left), shorts_contract.content_hash(right))

    def test_request_rejects_count_mismatch_and_duplicate_ids(self) -> None:
        request = valid_request()
        request["requestedCount"] = 2
        request["candidates"].append(deepcopy(request["candidates"][0]))
        with self.assertRaises(shorts_contract.ContractValidationError) as raised:
            shorts_contract.validate_document(request, "request")
        self.assertIn("candidate IDs", str(raised.exception))

        request["candidates"][1]["id"] = "02"
        request["candidates"].pop()
        with self.assertRaises(shorts_contract.ContractValidationError) as raised:
            shorts_contract.validate_document(request, "request")
        self.assertIn("requestedCount", str(raised.exception))

    def test_plan_hash_excludes_its_own_field_and_detects_change(self) -> None:
        plan = valid_plan()
        original = plan["planHash"]
        plan["planHash"] = "f" * 64
        self.assertEqual(shorts_contract.plan_hash(plan), original)
        plan["items"][0]["speed"] = 1.1
        self.assertNotEqual(shorts_contract.plan_hash(plan), original)

    def test_plan_status_mismatch_and_unapproved_plan_fail(self) -> None:
        plan = valid_plan()
        status = valid_status(plan)
        status["planHash"] = "f" * 64
        with self.assertRaises(shorts_contract.ContractValidationError):
            shorts_contract.ensure_plan_status_match(plan, status)

        plan["planApproval"] = {"status": "pending"}
        with self.assertRaises(shorts_contract.ContractValidationError):
            shorts_contract.require_plan_approval(plan)

    def test_atomic_json_write_replaces_complete_document(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            path = Path(tmp) / "shorts.status.json"
            shorts_contract.atomic_write_json(path, {"revision": 1})
            shorts_contract.atomic_write_json(path, {"revision": 2, "ok": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"ok": True, "revision": 2})
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
