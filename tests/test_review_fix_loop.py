from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from avo.timeline.review import run_fix_loop
from avo.timeline.review_runner import ReviewRunner
from tests.test_timeline_review_integration import FakeQc, FakeTranscript, FakeWatch


class FixLoopTests(unittest.TestCase):
    def test_safe_fix_creates_attempt_and_converges(self):
        state = {"n": 0}

        def inspect():
            return [] if state["n"] else [{"classification": "safe", "id": "f"}]

        def fix(_):
            state["n"] += 1
            return "r2"

        result = run_fix_loop(inspect, fix, max_attempts=3)
        self.assertEqual(result["state"], "ai-passed")
        self.assertEqual(result["attempts"][0]["fixRevision"], "r2")

    def test_identical_blocker_stops(self):
        result = run_fix_loop(
            lambda: [{"classification": "safe", "id": "same"}],
            lambda _: None,
            max_attempts=3,
        )
        self.assertEqual(result["state"], "blocked")

    def test_meaning_finding_never_calls_fix(self):
        calls = []
        result = run_fix_loop(
            lambda: [{"classification": "meaning", "id": "meaning"}],
            lambda findings: calls.append(findings),
        )
        self.assertEqual(result["state"], "needs-human-judgment")
        self.assertEqual(calls, [])

    def test_runner_rejects_safe_fix_without_changed_identity(self):
        class QcWithSafeFinding(FakeQc):
            def check(self, candidate: Path, **request):
                result = super().check(candidate, **request)
                result["findings"] = [
                    {"id": "layout", "classification": "safe", "message": "move card"}
                ]
                return result

        class NoOpFix:
            def apply_fix(self, findings, **request):
                return {
                    "candidate": str(request["candidate"]),
                    "dependencies": request["dependencies"],
                    "revisionId": "tracks-r0002",
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"candidate")
            result = ReviewRunner(
                review_root=root / "review",
                transcription=FakeTranscript(),
                watch=FakeWatch(),
                deterministic_qc=QcWithSafeFinding(),
                fix_executor=NoOpFix(),
                clock=lambda: "2026-08-13T00:00:00Z",
            ).run(
                checkpoint="cut-proof",
                candidate=candidate,
                dependencies={"cmap": "b" * 64, "sync-map": "c" * 64},
                render_profile="proof",
                risk_windows=[{"start": 0, "end": 1, "reason": "join"}],
            )
            self.assertEqual(result["state"], "blocked")
            self.assertIn("identity", result["blocker"])
