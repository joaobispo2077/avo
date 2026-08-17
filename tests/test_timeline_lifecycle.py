from __future__ import annotations

import unittest

from avo.timeline.lifecycle import (
    LifecycleError,
    PipelineRunStore,
    PipelineState,
    TransitionFacts,
    transition,
)


class TimelineLifecycleTests(unittest.TestCase):
    def test_happy_path_uses_canonical_order(self) -> None:
        state = PipelineState.INTAKE
        state = transition(state, PipelineState.SOURCES_READY, TransitionFacts())
        state = transition(
            state, PipelineState.SYNC_READY, TransitionFacts(sync_ready=True)
        )
        state = transition(
            state, PipelineState.CMAP_DRAFT, TransitionFacts(sync_ready=True)
        )
        self.assertEqual(state, PipelineState.CMAP_DRAFT)

    def test_bmap_requires_exact_approved_cmap_and_cut(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "approved CMap"):
            transition(
                PipelineState.CMAP_APPROVED,
                PipelineState.BMAP_DRAFT,
                TransitionFacts(cmap_approved=False),
            )
        with self.assertRaisesRegex(LifecycleError, "cut-output"):
            transition(
                PipelineState.CMAP_APPROVED,
                PipelineState.BMAP_DRAFT,
                TransitionFacts(cmap_approved=True, cut_output_hash=""),
            )

    def test_human_gate_requires_watch_and_current_transcript(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "Watch"):
            transition(
                PipelineState.CUT_AI_REVIEW,
                PipelineState.CMAP_APPROVED,
                TransitionFacts(transcript_current=True),
            )
        with self.assertRaisesRegex(LifecycleError, "transcript"):
            transition(
                PipelineState.CUT_AI_REVIEW,
                PipelineState.CMAP_APPROVED,
                TransitionFacts(watch_current=True),
            )

    def test_side_state_is_explicit(self) -> None:
        state = transition(
            PipelineState.ASSEMBLY_AI_REVIEW,
            PipelineState.BLOCKED,
            TransitionFacts(),
        )
        self.assertEqual(state, PipelineState.BLOCKED)

    def test_persisted_side_state_requires_explicit_recovery(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            values = iter(
                ["2026-08-13T12:00:00Z", "2026-08-13T12:01:00Z", "2026-08-13T12:02:00Z"]
            )
            store = PipelineRunStore(
                Path(tmp) / "pipeline-run.json", clock=lambda: next(values)
            )
            store.initialize(
                run_id="run",
                video_id="video",
                provider="bishop",
                project_path="avo.project.json",
            )
            blocked = store.enter_side_state(
                "blocked",
                actor="agent",
                reason="Watch unavailable",
                blockers=[{"code": "WATCH_UNAVAILABLE"}],
            )
            self.assertEqual(blocked["sideState"], "blocked")
            with self.assertRaisesRegex(LifecycleError, "explicit resume"):
                store.advance(
                    PipelineState.SOURCES_READY,
                    TransitionFacts(),
                    actor="agent",
                    reason="skip",
                )
            resumed = store.resume(
                actor="agent",
                reason="Watch installed",
                recovery_event={"tool": "watch"},
            )
            self.assertIsNone(resumed["sideState"])
            self.assertEqual(len(resumed["transitionHistory"]), 2)


if __name__ == "__main__":
    unittest.main()
