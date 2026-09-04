"""CLI-level planning and batch-state integration tests."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from avo import shorts, shorts_contract, shorts_media, shorts_plan
from avo.adapters.base import JobResult

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "shorts" / "planning"


class ShortsPlanningIntegrationTests(unittest.TestCase):
    def stage_request(self, root: Path, *, with_transcript: bool = True) -> Path:
        master = root / "master.mp4"
        master.write_bytes((FIXTURE_DIR / "master.mp4").read_bytes())
        if with_transcript:
            (root / "transcript.json").write_bytes(
                (FIXTURE_DIR / "transcript.json").read_bytes()
            )
        request = json.loads(
            (FIXTURE_DIR / "shorts.request.json").read_text(encoding="utf-8")
        )
        if not with_transcript:
            request["source"].pop("transcriptPath", None)
        path = root / "shorts.request.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        return path

    def test_v11_resolve_snapshots_external_request_into_canonical_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "footage"
            external = root / "incoming"
            raw_dir.mkdir()
            external.mkdir()
            request_path = self.stage_request(external)
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["version"] = "1.1"
            request["batchId"] = "canonical-demo"
            request["batchRoot"] = str(raw_dir / "edit" / "shorts" / "canonical-demo")
            request["batchRootSource"] = "canonical-default"
            request["source"].update({"sourceId": "master", "durationSec": 100})
            request["requestedCount"] = 1
            request["candidates"] = [request["candidates"][0]]
            candidate = request["candidates"][0]
            source_range = candidate.pop("sourceRange")
            candidate["sourceSegments"] = [
                {
                    "order": 1,
                    "sourceId": "master",
                    **source_range,
                    "rationale": "approved excerpt",
                    "evidenceReference": "review://segment-1",
                }
            ]
            request_path.write_text(json.dumps(request), encoding="utf-8")

            self.assertEqual(
                shorts.main(["resolve", str(request_path), "--raw-dir", str(raw_dir)]),
                shorts.EXIT_OK,
            )
            batch_root = raw_dir / "edit" / "shorts" / "canonical-demo"
            snapshot = batch_root / "shorts.request-v001.json"
            plan_path = batch_root / "plans" / "shorts.plan-v001.json"
            status_path = batch_root / "plans" / "shorts.status.json"
            self.assertTrue(snapshot.is_file())
            self.assertTrue(plan_path.is_file())
            self.assertTrue(status_path.is_file())
            snapped = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertTrue(Path(snapped["source"]["masterPath"]).is_absolute())
            self.assertEqual(
                json.loads(plan_path.read_text(encoding="utf-8"))["batchRoot"],
                str(batch_root.resolve()),
            )
            index = json.loads(
                (raw_dir / "edit" / "shorts" / "shorts.index.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(index["batches"][0]["batchId"], "canonical-demo")

    def test_validate_and_resolve_create_only_an_immutable_pending_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = self.stage_request(root)
            plan_path = root / "plans" / "shorts.plan-v001.json"
            self.assertEqual(shorts.main(["validate", str(request_path)]), 0)
            self.assertEqual(
                shorts.main(["resolve", str(request_path), "-o", str(plan_path)]), 0
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["resolvedCount"], 10)
            self.assertEqual(plan["planApproval"]["status"], "pending")
            self.assertFalse((root / "proofs").exists())
            self.assertFalse((root / "delivery").exists())
            self.assertEqual(
                shorts.main(["build", str(plan_path), "--stage", "proof"]),
                shorts.EXIT_APPROVAL_REQUIRED,
            )

    def test_unchanged_resolve_reuses_same_plan_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = self.stage_request(root)
            plan_path = root / "plans" / "shorts.plan-v001.json"
            first = shorts_plan.resolve_request_file(request_path, plan_path)
            second = shorts_plan.resolve_request_file(request_path, plan_path)
            self.assertEqual(first, second)
            self.assertEqual(list(plan_path.parent.glob("*.json")), [plan_path])

    def test_missing_transcript_routes_through_injected_transcriber(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = self.stage_request(root, with_transcript=False)
            calls: list[Path] = []

            def fake_transcriber(master: Path, edit_dir: Path) -> Path:
                calls.append(master)
                output = edit_dir / "transcripts" / "master.json"
                output.parent.mkdir(parents=True)
                output.write_bytes((FIXTURE_DIR / "transcript.json").read_bytes())
                return output

            plan_path = root / "plans" / "shorts.plan-v001.json"
            shorts_plan.resolve_request_file(
                request_path,
                plan_path,
                transcribe_runner=fake_transcriber,
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].resolve(), (root / "master.mp4").resolve())
            self.assertTrue(plan_path.is_file())

    def approve_plan(self, plan_path: Path) -> None:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["planApproval"] = {
            "status": "approved",
            "reference": "human-review:batch-plan",
            "timestamp": "2026-08-12T12:00:00Z",
        }
        plan["planHash"] = shorts_contract.plan_hash(plan)
        shorts_contract.atomic_write_json(plan_path, plan)

    def fake_prepare(self, source: Path, output_dir: Path, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        duration = (kwargs["end_sec"] - kwargs["start_sec"]) / kwargs["speed"]
        result = {}
        for key, name, muted in (
            ("baseVideo", "base-video.mp4", True),
            ("dialogueAudio", "dialogue-audio.m4a", False),
        ):
            path = output_dir / name
            path.write_bytes(f"{key}:{duration}".encode())
            result[key] = shorts_media.PreparedAsset(
                path, hashlib.sha256(path.read_bytes()).hexdigest(), duration, muted
            )
        return result

    def test_proof_build_is_immutable_selective_and_non_fail_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = self.stage_request(root)
            plan_path = root / "plans" / "shorts.plan-v001.json"
            shorts_plan.resolve_request_file(request_path, plan_path)
            self.approve_plan(plan_path)
            calls = []

            class FakeAdapter:
                def execute(self, operation, project, *extra, **kwargs):
                    calls.append((operation, project))
                    if operation == "render":
                        output = Path(extra[extra.index("--output") + 1])
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(b"proof")
                    return JobResult(exit_code=0)

            _, first = shorts.build_proofs(
                plan_path,
                workers=3,
                prepare=self.fake_prepare,
                adapter_factory=FakeAdapter,
            )
            self.assertEqual(first["batchState"], "proofs-ready")
            self.assertEqual({item["proofRevision"] for item in first["items"]}, {1})
            first_proof_hashes = {
                item["shortId"]: next(
                    a["hash"] for a in item["artifacts"] if a["kind"] == "proof"
                )
                for item in first["items"]
            }
            call_count = len(calls)
            _, _unchanged = shorts.build_proofs(
                plan_path,
                workers=2,
                prepare=self.fake_prepare,
                adapter_factory=FakeAdapter,
            )
            self.assertEqual(len(calls), call_count)
            status_path = plan_path.with_name("shorts.status.json")
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["items"][2]["dirty"] = True
            status["items"][2]["dirtyReasons"] = ["caption-policy-changed"]
            shorts_contract.atomic_write_json(status_path, status)
            _, revised = shorts.build_proofs(
                plan_path,
                short_ids=["03"],
                workers=1,
                prepare=self.fake_prepare,
                adapter_factory=FakeAdapter,
            )
            revisions = {
                item["shortId"]: item["proofRevision"] for item in revised["items"]
            }
            self.assertEqual(revisions["03"], 2)
            self.assertEqual(revisions["01"], 1)
            self.assertEqual(
                first_proof_hashes["01"],
                next(
                    a["hash"]
                    for a in revised["items"][0]["artifacts"]
                    if a["kind"] == "proof"
                ),
            )

    def test_explicit_loudness_preset_normalizes_before_artifact_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = self.stage_request(root)
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["candidates"] = request["candidates"][:1]
            request["requestedCount"] = 1
            request["output"]["loudnessPreset"] = "youtube_shorts"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            plan_path = root / "plans" / "shorts.plan-v001.json"
            shorts_plan.resolve_request_file(request_path, plan_path)
            self.approve_plan(plan_path)

            class FakeAdapter:
                def execute(self, operation, project, *extra, **kwargs):
                    if operation == "render":
                        output = Path(extra[extra.index("--output") + 1])
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(b"unnormalized")
                    return JobResult(exit_code=0)

            def fake_normalize(input_path, output_path, **kwargs):
                self.assertEqual(input_path.read_bytes(), b"unnormalized")
                self.assertEqual(kwargs["preset_id"], "youtube_shorts")
                output_path.write_bytes(b"normalized")
                return True

            with unittest.mock.patch.object(
                shorts, "_apply_loudness_preset", side_effect=fake_normalize
            ):
                _, status = shorts.build_proofs(
                    plan_path,
                    workers=1,
                    prepare=self.fake_prepare,
                    adapter_factory=FakeAdapter,
                )

            proof = next(
                artifact
                for artifact in status["items"][0]["artifacts"]
                if artifact["kind"] == "proof"
            )
            self.assertEqual(Path(proof["path"]).read_bytes(), b"normalized")
            self.assertEqual(proof["hash"], hashlib.sha256(b"normalized").hexdigest())

    def test_one_render_failure_does_not_cancel_approved_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = self.stage_request(root)
            plan_path = root / "plans" / "shorts.plan-v001.json"
            shorts_plan.resolve_request_file(request_path, plan_path)
            self.approve_plan(plan_path)

            class PartialAdapter:
                def execute(self, operation, project, *extra, **kwargs):
                    if operation == "render" and "05" in str(project).replace(
                        "\\", "/"
                    ):
                        return JobResult(exit_code=7, stderr="synthetic render failure")
                    if operation == "render":
                        output = Path(extra[extra.index("--output") + 1])
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(b"proof")
                    return JobResult(exit_code=0)

            _, status = shorts.build_proofs(
                plan_path,
                workers=4,
                prepare=self.fake_prepare,
                adapter_factory=PartialAdapter,
            )
            states = {item["shortId"]: item["state"] for item in status["items"]}
            self.assertEqual(status["batchState"], "proof-partial")
            self.assertEqual(states["05"], "failed")
            self.assertEqual(states["04"], "proof-ready")
            self.assertEqual(states["06"], "proof-ready")

    def test_preview_build_marks_dirty_for_full_resolution_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = self.stage_request(root)
            plan_path = root / "plans" / "shorts.plan-v001.json"
            shorts_plan.resolve_request_file(request_path, plan_path)
            self.approve_plan(plan_path)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))

            class FakeAdapter:
                def execute(self, operation, project, *extra, **kwargs):
                    if operation == "render":
                        output = Path(extra[extra.index("--output") + 1])
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(b"proof")
                    return JobResult(exit_code=0)

            _, preview_status = shorts.build_proofs(
                plan_path,
                workers=2,
                preview=True,
                prepare=self.fake_prepare,
                adapter_factory=FakeAdapter,
            )
            self.assertTrue(
                all(
                    item["renderProfile"]["preview"] for item in preview_status["items"]
                )
            )
            dirty = shorts_plan.dirty_items(plan, preview_status, preview=False)
            self.assertEqual(len(dirty), 10)
            self.assertIn("render-profile-changed", dirty["01"])
            _, full_status = shorts.build_proofs(
                plan_path,
                workers=2,
                preview=False,
                prepare=self.fake_prepare,
                adapter_factory=FakeAdapter,
            )
            self.assertEqual(
                {item["proofRevision"] for item in full_status["items"]}, {2}
            )
            self.assertFalse(full_status["items"][0]["renderProfile"]["preview"])
            self.assertEqual(full_status["items"][0]["renderProfile"]["width"], 1080)

    def test_qc_cli_populates_batch_qc_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = self.stage_request(root)
            plan_path = root / "plans" / "shorts.plan-v001.json"
            shorts_plan.resolve_request_file(request_path, plan_path)
            self.approve_plan(plan_path)

            class FakeAdapter:
                def execute(self, operation, project, *extra, **kwargs):
                    if operation == "render":
                        output = Path(extra[extra.index("--output") + 1])
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(b"proof")
                    return JobResult(exit_code=0)

            shorts.build_proofs(
                plan_path,
                workers=1,
                prepare=self.fake_prepare,
                adapter_factory=FakeAdapter,
            )
            with unittest.mock.patch.object(
                shorts.shorts_qc,
                "qc_proof_artifact",
                return_value={"status": "passed", "findings": []},
            ):
                self.assertEqual(
                    shorts.main(["qc", str(plan_path), "--stage", "proof"]),
                    shorts.EXIT_OK,
                )
            status = json.loads(
                plan_path.with_name("shorts.status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(status["batchQcSummary"]["passed"], 10)
            self.assertEqual(status["batchQcSummary"]["failed"], 0)

    def test_promote_cli_writes_delivery_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = self.stage_request(root)
            plan_path = root / "plans" / "shorts.plan-v001.json"
            shorts_plan.resolve_request_file(request_path, plan_path)
            self.approve_plan(plan_path)

            class FakeAdapter:
                def execute(self, operation, project, *extra, **kwargs):
                    if operation == "render":
                        output = Path(extra[extra.index("--output") + 1])
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(b"proof")
                    return JobResult(exit_code=0)

            shorts.build_proofs(
                plan_path,
                workers=1,
                prepare=self.fake_prepare,
                adapter_factory=FakeAdapter,
            )
            status_path = plan_path.with_name("shorts.status.json")
            status = json.loads(status_path.read_text(encoding="utf-8"))
            for item in status["items"]:
                item["state"] = "proof-approved"
                item["qc"] = {"status": "passed", "findings": []}
            shorts_contract.atomic_write_json(status_path, status)
            manifest_path = root / "approvals.json"
            current_proofs = {
                item["shortId"]: next(
                    artifact
                    for artifact in reversed(item["artifacts"])
                    if artifact["kind"] == "proof"
                    and artifact["revision"] == item["proofRevision"]
                )
                for item in status["items"]
            }
            first_item = status["items"][0]
            first_proof = current_proofs[first_item["shortId"]]
            manifest_path.write_text(
                json.dumps(
                    {
                        "approvals": [
                            {
                                "gate": gate,
                                "status": "approved",
                                "reference": f"review://{gate}",
                                "timestamp": "2026-08-12T12:00:00Z",
                                "candidateHash": first_proof["hash"],
                                "candidateIdentityHash": "a" * 64,
                                "dependencyLockSha256": "b" * 64,
                                "evidenceBundleSha256": "c" * 64,
                                "proofRevision": first_item["proofRevision"],
                            }
                            for gate in (
                                "batch-plan",
                                "motion-proof",
                                "picture-lock",
                                "rights",
                                "pre-master",
                            )
                        ],
                        "watchReviews": [
                            {
                                "shortId": item["shortId"],
                                "candidateHash": current_proofs[item["shortId"]][
                                    "hash"
                                ],
                                "candidateIdentityHash": "d" * 64,
                                "dependencyLockSha256": "e" * 64,
                                "evidenceBundleSha256": "f" * 64,
                                "proofRevision": item["proofRevision"],
                                "reference": f"watch://{item['shortId']}/proof-v{item['proofRevision']:03d}",
                            }
                            for item in status["items"]
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_transcript(master: Path, edit_dir: Path) -> dict[str, Path]:
                transcript_dir = edit_dir / "transcripts"
                transcript_dir.mkdir(parents=True, exist_ok=True)
                outputs = {}
                for kind in ("json", "srt", "txt", "md"):
                    path = transcript_dir / f"{master.stem}.{kind}"
                    path.write_text(f"{master.name}:{kind}", encoding="utf-8")
                    outputs[kind] = path
                return outputs

            with unittest.mock.patch(
                "avo.final_transcript_artifacts.generate_from_master",
                fake_transcript,
            ):
                self.assertEqual(
                    shorts.main(
                        [
                            "promote",
                            str(plan_path),
                            "--approval-manifest",
                            str(manifest_path),
                            "--delivery-dir",
                            str(root / "delivery"),
                        ]
                    ),
                    shorts.EXIT_OK,
                )
            self.assertTrue((root / "delivery" / "delivery-manifest.json").is_file())
            with unittest.mock.patch.object(
                shorts.shorts_qc,
                "qc_proof_artifact",
                return_value={"status": "passed", "findings": []},
            ):
                self.assertEqual(
                    shorts.main(["qc", str(plan_path), "--stage", "master"]),
                    shorts.EXIT_OK,
                )
            delivered = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertTrue(delivered["deliveryComplete"])
            self.assertEqual(delivered["batchState"], "delivered")
            self.assertTrue(
                all(item["state"] == "delivered" for item in delivered["items"])
            )


if __name__ == "__main__":
    unittest.main()
