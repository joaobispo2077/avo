from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from avo import shorts_contract, shorts_delivery, shorts_plan
from avo.shorts_paths import resolve_shorts_batch_paths

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "shorts" / "planning"


class ShortsPreservePathsTests(unittest.TestCase):
    def test_keeps_index_contracts_approvals_and_delivery_not_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            shorts_root = raw / "edit" / "shorts"
            batch = shorts_root / "campaign" / "demo-batch"
            (batch / "work" / "01" / "proof-v001").mkdir(parents=True)
            (batch / "delivery" / "masters").mkdir(parents=True)
            (batch / "approvals" / "rights").mkdir(parents=True)
            (batch / "plans").mkdir(parents=True)
            index = shorts_root / "shorts.index.json"
            index.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0.0",
                        "batches": [
                            {
                                "batchId": "demo-batch",
                                "batchRoot": str(batch),
                                "batchRootSource": "invocation",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (batch / "shorts.request-v001.json").write_text("{}", encoding="utf-8")
            (batch / "plans" / "shorts.plan-v001.json").write_text(
                "{}", encoding="utf-8"
            )
            (batch / "plans" / "shorts.status.json").write_text("{}", encoding="utf-8")
            approval = batch / "approvals" / "rights" / "approval-v001.json"
            approval.write_text("{}", encoding="utf-8")
            master = batch / "delivery" / "masters" / "demo-short-01-master-v001.mp4"
            master.write_bytes(b"master")
            proof = batch / "work" / "01" / "proof-v001" / "out.mp4"
            proof.write_bytes(b"proof")
            kept = {
                path.resolve() for path in shorts_delivery.preserved_shorts_paths(raw)
            }
            self.assertIn(index.resolve(), kept)
            self.assertIn(master.resolve(), kept)
            self.assertIn(approval.resolve(), kept)
            self.assertIn((batch / "shorts.request-v001.json").resolve(), kept)
            self.assertIn((batch / "plans" / "shorts.plan-v001.json").resolve(), kept)
            self.assertIn((batch / "plans" / "shorts.status.json").resolve(), kept)
            self.assertNotIn(proof.resolve(), kept)

    def test_rejects_indexed_root_outside_project_shorts_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            shorts_root = raw / "edit" / "shorts"
            shorts_root.mkdir(parents=True)
            (shorts_root / "shorts.index.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0.0",
                        "batches": [
                            {
                                "batchId": "demo-batch",
                                "batchRoot": str(raw / "external" / "demo-batch"),
                                "batchRootSource": "invocation",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(shorts_delivery.DeliveryError):
                shorts_delivery.preserved_shorts_paths(raw)


class ShortsDeliveryTests(unittest.TestCase):
    def plan_and_status(self, root: Path):
        request = json.loads((FIXTURE_DIR / "shorts.request.json").read_text())
        transcript = json.loads((FIXTURE_DIR / "transcript.json").read_text())
        plan = shorts_plan.resolve_batch(
            request, transcript, request_path=root / "request.json"
        )
        items = []
        for item in plan["items"]:
            proof = root / f"{item['id']}.mp4"
            proof.write_bytes(f"proof-{item['id']}".encode())
            items.append(
                {
                    "shortId": item["id"],
                    "inputFingerprint": item["inputFingerprint"],
                    "state": "proof-approved",
                    "dirty": False,
                    "dirtyReasons": [],
                    "proofRevision": 1,
                    "masterRevision": 0,
                    "artifacts": [
                        {
                            "kind": "proof",
                            "path": str(proof),
                            "hash": hashlib.sha256(proof.read_bytes()).hexdigest(),
                            "revision": 1,
                        }
                    ],
                    "errors": [],
                    "qc": {"status": "passed"},
                }
            )
        approvals = [
            {
                "gate": gate,
                "status": "approved",
                "reference": f"review://{gate}",
                "timestamp": "2026-08-12T12:00:00Z",
            }
            for gate in (
                "batch-plan",
                "motion-proof",
                "picture-lock",
                "rights",
                "pre-master",
            )
        ]
        status = {
            "version": "1.0",
            "batchId": plan["batchId"],
            "planPath": str(root / "plan.json"),
            "planHash": plan["planHash"],
            "batchState": "picture-locked",
            "updatedAt": "2026-08-12T12:00:00Z",
            "items": items,
            "batchApprovals": approvals,
            "blockingRisks": [],
            "batchQcSummary": None,
            "deliveryComplete": False,
        }
        return plan, status

    def test_missing_gate_blocks_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _plan, status = self.plan_and_status(Path(tmp))
            status["batchApprovals"] = status["batchApprovals"][:-1]
            with self.assertRaises(shorts_delivery.DeliveryError):
                shorts_delivery.ensure_promotable(status)

    def test_promotion_is_immutable_hashed_and_has_four_exact_master_sidecars(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, status = self.plan_and_status(root)

            def transcript(master: Path, edit_dir: Path):
                transcript_dir = edit_dir / "transcripts"
                transcript_dir.mkdir(parents=True, exist_ok=True)
                outputs = {}
                for kind in ("json", "srt", "txt", "md"):
                    path = transcript_dir / f"{master.stem}.{kind}"
                    path.write_text(f"{master.name}:{kind}")
                    outputs[kind] = path
                return outputs

            result = shorts_delivery.promote_batch(
                plan, status, root / "delivery", transcript_generator=transcript
            )
            self.assertEqual(len(result["manifest"]["items"]), 10)
            self.assertTrue(result["status"]["deliveryComplete"])
            self.assertTrue(
                all(len(row["transcripts"]) == 4 for row in result["manifest"]["items"])
            )
            self.assertTrue(
                all(
                    Path(sidecar["path"]).parent == root / "delivery" / "transcripts"
                    for row in result["manifest"]["items"]
                    for sidecar in row["transcripts"]
                )
            )
            first = result["manifest"]["items"][0]
            self.assertEqual(
                first["sha256"],
                hashlib.sha256(Path(first["masterPath"]).read_bytes()).hexdigest(),
            )
            with self.assertRaises(shorts_delivery.DeliveryError):
                shorts_delivery.promote_batch(
                    plan,
                    result["status"],
                    root / "delivery",
                    transcript_generator=transcript,
                )

    def test_v11_delivery_embeds_lineage_insertions_and_release_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Path(__file__).parent / "fixtures" / "shorts" / "planning-v11"
            request = json.loads(
                (fixture / "shorts.request.json").read_text(encoding="utf-8")
            )
            paths = resolve_shorts_batch_paths(root, request["batchId"])
            request["batchRoot"] = str(paths.batch_root)
            request["defaults"]["delivery"] = {
                "rightsEvidence": ["rights://source-license"],
                "sponsorshipDisclosure": "not-sponsored",
                "affiliateDisclosure": "affiliate-links-declared",
                "reviewUnitDisclosure": "not-a-review-unit",
                "privacyEvidence": ["privacy://faces-cleared"],
                "safetyEvidence": ["safety://review-passed"],
                "consentEvidence": ["consent://speaker-release"],
                "aiUseEvidence": ["ai://caption-assistance-disclosed"],
            }
            request["insertions"] = [
                {
                    "id": "support",
                    "sourcePath": "support.mp4",
                    "sourceFingerprint": "c" * 64,
                    "videoStream": "0:v:0",
                    "approvedWindows": [{"startSec": 0, "endSec": 10}],
                    "excludedWindows": [],
                    "repeatMode": "finite-repeat",
                    "supportVolume": 0,
                    "layoutRole": "secondary-pane",
                    "rightsBasis": "rights://support-license",
                    "semanticApprovalReference": "review://support",
                    "allocation": {
                        "mode": "explicit",
                        "candidateIds": ["01"],
                    },
                }
            ]
            request_path = root / "shorts.request-v001.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            transcript = json.loads(
                (fixture / "transcript.json").read_text(encoding="utf-8")
            )
            plan = shorts_plan.resolve_batch(
                request,
                transcript,
                request_path=request_path,
                source_fingerprint="a" * 64,
                provider_tokens={},
            )
            item = plan["items"][0]
            proof = root / "proof.mp4"
            proof.write_bytes(b"proof")
            insertion_video = root / "insertion.mp4"
            insertion_video.write_bytes(b"insertion")
            lineage = {
                "planHash": plan["planHash"],
                "shortId": item["id"],
                "sourceSegments": item["sourceSegments"],
                "preparedVideo": {"hash": "d" * 64, "durationSec": 6},
                "preparedDialogue": {"hash": "e" * 64, "durationSec": 6},
                "joinWindows": [
                    {"start": 1.985, "end": 2.015, "reason": "segment seam"},
                    {"start": 3.985, "end": 4.015, "reason": "segment seam"},
                ],
            }
            lineage["lineageHash"] = shorts_contract.content_hash(lineage)
            lineage_path = root / "prepared-lineage.json"
            lineage_path.write_text(json.dumps(lineage), encoding="utf-8")
            artifacts = [
                {
                    "kind": "proof",
                    "path": str(proof),
                    "hash": hashlib.sha256(proof.read_bytes()).hexdigest(),
                    "revision": 1,
                },
                {
                    "kind": "prepared-lineage",
                    "path": str(lineage_path),
                    "hash": hashlib.sha256(lineage_path.read_bytes()).hexdigest(),
                    "revision": 1,
                },
                {
                    "kind": "prepared-insertion-video",
                    "path": str(insertion_video),
                    "hash": hashlib.sha256(insertion_video.read_bytes()).hexdigest(),
                    "revision": 1,
                },
            ]
            status = {
                "version": "1.1",
                "batchId": plan["batchId"],
                "batchState": "picture-locked",
                "deliveryComplete": False,
                "batchApprovals": [
                    {
                        "gate": gate,
                        "status": "approved",
                        "reference": f"review://{gate}",
                    }
                    for gate in (
                        "batch-plan",
                        "motion-proof",
                        "picture-lock",
                        "rights",
                        "pre-master",
                    )
                ],
                "items": [
                    {
                        "shortId": "01",
                        "state": "proof-approved",
                        "dirty": False,
                        "proofRevision": 1,
                        "masterRevision": 0,
                        "qc": {"status": "passed"},
                        "artifacts": artifacts,
                    }
                ],
            }

            def transcript(master: Path, edit_dir: Path) -> dict[str, Path]:
                output = edit_dir / "transcripts" / f"{master.stem}.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("{}", encoding="utf-8")
                return {"json": output}

            result = shorts_delivery.promote_batch(
                plan,
                status,
                paths.delivery_dir,
                transcript_generator=transcript,
                batch_paths=paths,
                approval_snapshot={"path": "approval.json", "sha256": "f" * 64},
            )
            manifest = result["manifest"]
            delivered = manifest["items"][0]
            self.assertNotIn("sourceRange", delivered)
            self.assertEqual(
                [row["startSec"] for row in delivered["sourceSegments"]],
                [10.0, 30.0, 20.0],
            )
            self.assertEqual(
                delivered["preparedLineage"]["joinWindows"], lineage["joinWindows"]
            )
            self.assertEqual(
                delivered["insertionLineage"]["rightsBasis"],
                "rights://support-license",
            )
            self.assertEqual(
                delivered["insertionLineage"]["preparedArtifacts"][0]["hash"],
                hashlib.sha256(insertion_video.read_bytes()).hexdigest(),
            )
            evidence = manifest["releaseEvidence"]
            self.assertEqual(evidence["disclosures"]["sponsorship"], "not-sponsored")
            self.assertEqual(evidence["privacy"], ["privacy://faces-cleared"])
            self.assertEqual(evidence["safety"], ["safety://review-passed"])
            self.assertEqual(evidence["consent"], ["consent://speaker-release"])
            self.assertEqual(evidence["aiUse"], ["ai://caption-assistance-disclosed"])
            self.assertIn(
                '"startSec": 10',
                (paths.delivery_dir / "EDITLOG.md").read_text(),
            )
            source_log = (paths.delivery_dir / "SOURCE-LOG.md").read_text()
            self.assertIn("rights://support-license", source_log)
            self.assertIn("consent://speaker-release", source_log)


if __name__ == "__main__":
    unittest.main()
