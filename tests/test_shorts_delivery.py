from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from avo import shorts_delivery, shorts_plan


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "shorts" / "planning"


class ShortsDeliveryTests(unittest.TestCase):
    def plan_and_status(self, root: Path):
        request = json.loads((FIXTURE_DIR / "shorts.request.json").read_text())
        transcript = json.loads((FIXTURE_DIR / "transcript.json").read_text())
        plan = shorts_plan.resolve_batch(request, transcript, request_path=root / "request.json")
        items = []
        for item in plan["items"]:
            proof = root / f"{item['id']}.mp4"
            proof.write_bytes(f"proof-{item['id']}".encode())
            items.append({
                "shortId": item["id"], "inputFingerprint": item["inputFingerprint"],
                "state": "proof-approved", "dirty": False, "dirtyReasons": [],
                "proofRevision": 1, "masterRevision": 0,
                "artifacts": [{"kind": "proof", "path": str(proof), "hash": hashlib.sha256(proof.read_bytes()).hexdigest(), "revision": 1}],
                "errors": [], "qc": {"status": "passed"},
            })
        approvals = [{"gate": gate, "status": "approved", "reference": f"review://{gate}", "timestamp": "2026-08-12T12:00:00Z"} for gate in ("batch-plan", "motion-proof", "picture-lock", "rights", "pre-master")]
        status = {"version": "1.0", "batchId": plan["batchId"], "planPath": str(root / "plan.json"), "planHash": plan["planHash"], "batchState": "picture-locked", "updatedAt": "2026-08-12T12:00:00Z", "items": items, "batchApprovals": approvals, "blockingRisks": [], "batchQcSummary": None, "deliveryComplete": False}
        return plan, status

    def test_missing_gate_blocks_promotion(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            plan, status = self.plan_and_status(Path(tmp))
            status["batchApprovals"] = status["batchApprovals"][:-1]
            with self.assertRaises(shorts_delivery.DeliveryError):
                shorts_delivery.ensure_promotable(status)

    def test_promotion_is_immutable_hashed_and_has_four_exact_master_sidecars(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            root = Path(tmp)
            plan, status = self.plan_and_status(root)
            def transcript(master: Path, edit_dir: Path):
                outputs = {}
                for kind in ("json", "srt", "txt", "md"):
                    path = edit_dir / f"{master.stem}.{kind}"
                    path.write_text(f"{master.name}:{kind}")
                    outputs[kind] = path
                return outputs
            result = shorts_delivery.promote_batch(plan, status, root / "delivery", transcript_generator=transcript)
            self.assertEqual(len(result["manifest"]["items"]), 10)
            self.assertTrue(result["status"]["deliveryComplete"])
            self.assertTrue(all(len(row["transcripts"]) == 4 for row in result["manifest"]["items"]))
            first = result["manifest"]["items"][0]
            self.assertEqual(first["sha256"], hashlib.sha256(Path(first["masterPath"]).read_bytes()).hexdigest())
            with self.assertRaises(shorts_delivery.DeliveryError):
                shorts_delivery.promote_batch(plan, result["status"], root / "delivery", transcript_generator=transcript)


if __name__ == "__main__":
    unittest.main()
