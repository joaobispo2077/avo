from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from avo.timeline.animation import AnimationError, AnimationService
from avo.timeline.provider_animation import ProviderAnimationService
from tests.test_animation_promotion import pattern


class RecommendTests(unittest.TestCase):
    def test_diagnosis_required(self):
        with self.assertRaises(AnimationError):
            AnimationService.recommend(
                {"patterns": [], "events": []}, {}, evidence_sha256="a" * 64
            )

    def test_compatible_only_and_rejection_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ProviderAnimationService(
                Path(tmp) / "animation.json",
                provider="bishop",
                clock=lambda: "2026-08-13T00:00:00Z",
            )
            proposal = service.propose(
                pattern(), actor="creator", intent_reference="intent"
            )
            service.decide(
                Path(proposal["path"]),
                decision="approved",
                actor="creator",
                reason="approved",
            )
            diagnosis = {"format": "talking-head-review", "constraints": []}
            evidence = "b" * 64
            self.assertEqual(
                [
                    item["patternId"]
                    for item in AnimationService.recommend(
                        service.load(), diagnosis, evidence_sha256=evidence
                    )
                ],
                ["c01-c02"],
            )
            service.reject_recommendation(
                pattern_id="c01-c02",
                evidence_sha256=evidence,
                actor="creator",
                reason="not this video",
            )
            self.assertEqual(
                AnimationService.recommend(
                    service.load(), diagnosis, evidence_sha256=evidence
                ),
                [],
            )
            self.assertEqual(
                [
                    item["patternId"]
                    for item in AnimationService.recommend(
                        service.load(), diagnosis, evidence_sha256="c" * 64
                    )
                ],
                ["c01-c02"],
            )
