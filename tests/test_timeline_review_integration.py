from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from avo.timeline.lifecycle import PipelineState, TransitionFacts, transition
from avo.timeline.ports import ToolError
from avo.timeline.review import GateError, evaluate_gate
from avo.timeline.review_runner import ReviewRunner


class FakeTranscript:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    def transcribe(self, candidate: Path, **options):
        if self.fail:
            raise ToolError("TRANSCRIPTION_UNAVAILABLE", "offline", True, "install model")
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        return {
            "status": "pass",
            "sourceSha256": digest,
            "transcriptPath": "",
            "engine": "fixture",
            "engineVersion": "1",
            "model": "ptbr",
            "language": "pt-BR",
            "words": [{"start": 0.0, "end": 1.0, "word": "oi", "probability": 1.0}],
            "findings": [],
        }


class FakeWatch:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.requests = []

    def review(self, candidate: Path, **request):
        self.requests.append(request)
        if self.fail:
            raise ToolError("WATCH_UNAVAILABLE", "offline", True, "install Watch")
        windows = request["windows"]
        return {
            "status": "pass",
            "coverage": {"mode": "full", "windows": windows},
            "findings": [],
            "tool": "watch-fixture",
            "toolVersion": "1",
            "model": "fixture",
            "artifacts": [],
        }


class FakeQc:
    def check(self, candidate: Path, **request):
        return {
            "status": "pass",
            "duration": 2.0,
            "coverage": {"mode": "full", "windows": request["risk_windows"]},
            "tool": "qc-fixture",
            "toolVersion": "1",
            "findings": [],
            "evidence": [
                {"kind": "lineage", "status": "pass", "findings": []},
                {"kind": "technical-qc", "status": "pass", "findings": []},
                {"kind": "sync", "status": "pass", "findings": []},
            ],
        }


class ReviewIntegrationTests(unittest.TestCase):
    def test_current_candidate_runs_transcript_watch_and_qc_before_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"candidate")
            watch = FakeWatch()
            runner = ReviewRunner(
                review_root=root / "review",
                transcription=FakeTranscript(),
                watch=watch,
                deterministic_qc=FakeQc(),
                clock=lambda: "2026-08-13T00:00:00Z",
            )
            windows = [
                {"start": 0.4, "end": 0.6, "reason": "join"},
                {"start": 1.2, "end": 1.4, "reason": "privacy"},
            ]
            result = runner.run(
                checkpoint="cut-proof",
                candidate=candidate,
                dependencies={"cmap": "b" * 64, "sync-map": "c" * 64},
                render_profile="proof",
                risk_windows=windows,
            )
            self.assertEqual(result["state"], "ai-passed")
            self.assertEqual(
                {item["kind"] for item in result["evidence"]},
                {"lineage", "technical-qc", "sync", "transcript-analysis", "watch"},
            )
            self.assertEqual(watch.requests[0]["windows"], windows)
            self.assertTrue(result["reviewPath"].is_file())
            self.assertTrue(result["approvalGatePath"].is_file())
            self.assertIn("changeSummary", result)
            self.assertTrue(result["changeSummary"]["items"])
            self.assertEqual(result["changeSummary"]["windows"], windows)

    def test_tool_outage_blocks_without_human_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"candidate")
            runner = ReviewRunner(
                review_root=root / "review",
                transcription=FakeTranscript(),
                watch=FakeWatch(fail=True),
                deterministic_qc=FakeQc(),
                clock=lambda: "2026-08-13T00:00:00Z",
            )
            result = runner.run(
                checkpoint="cut-proof",
                candidate=candidate,
                dependencies={"cmap": "b" * 64, "sync-map": "c" * 64},
                render_profile="proof",
                risk_windows=[{"start": 0, "end": 1, "reason": "join"}],
            )
            self.assertEqual(result["state"], "blocked")
            self.assertIsNone(result["approvalGatePath"])
            self.assertEqual(len([a for a in result["attempts"] if a["producer"] == "watch"]), 3)

    def test_duplicate_current_evidence_blocks_gate(self):
        evidence = [
            {
                "kind": kind,
                "status": "pass",
                "candidateHash": "a" * 64,
                "candidateIdentityHash": "d" * 64,
                "dependencyHashes": {"cmap": "b" * 64, "sync-map": "c" * 64},
                "dependencyLockSha256": "e" * 64,
            }
            for kind in ("lineage", "technical-qc", "sync", "transcript-analysis", "watch", "watch")
        ]
        with self.assertRaises(GateError):
            evaluate_gate(
                "cut-proof",
                "a" * 64,
                {"cmap": "b" * 64, "sync-map": "c" * 64},
                evidence,
                candidate_identity_hash="d" * 64,
                dependency_lock_sha256="e" * 64,
            )

    def test_ai_gate_unlocks_exact_human_transition(self):
        evidence = [
            {
                "kind": kind,
                "status": "pass",
                "candidateHash": "a" * 64,
                "candidateIdentityHash": "d" * 64,
                "dependencyHashes": {"cmap": "b" * 64, "sync-map": "c" * 64},
                "dependencyLockSha256": "e" * 64,
                "scope": {"mode": "full"},
                "coverage": {"requiredWindows": 0, "reviewedWindows": 0},
            }
            for kind in ("lineage", "technical-qc", "sync", "transcript-analysis", "watch")
        ]
        evaluate_gate(
            "cut-proof",
            "a" * 64,
            {"cmap": "b" * 64, "sync-map": "c" * 64},
            evidence,
            candidate_identity_hash="d" * 64,
            dependency_lock_sha256="e" * 64,
        )
        self.assertEqual(
            transition(
                PipelineState.CUT_AI_REVIEW,
                PipelineState.CMAP_APPROVED,
                TransitionFacts(watch_current=True, transcript_current=True),
            ),
            PipelineState.CMAP_APPROVED,
        )
