from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from avo.timeline.animation import AnimationError
from avo.timeline.provider_animation import ProviderAnimationService


def pattern() -> dict:
    return {
        "patternId": "c01-c02",
        "name": "Chapter identification pair",
        "version": "1.0.0",
        "behavior": {
            "sequence": ["chapter-identification", "topic-card"],
            "motion": ["tremble-entry", "readable-hold", "resolved-exit"],
        },
        "contexts": ["talking-head-review"],
        "exclusions": ["evidence-fullscreen"],
        "requiredAssets": ["chapter-label", "topic-label"],
        "accessibility": {"reducedMotion": True, "flashingSafe": True},
        "provenance": {
            "sourceVideoId": "example-source-video",
            "candidateSha256": "a" * 64,
            "sectionRefs": ["C01", "C02"],
        },
    }


class PromotionTests(unittest.TestCase):
    def test_project_content_and_media_paths_rejected(self):
        bad = pattern()
        bad["behavior"]["text"] = "project claim"
        with tempfile.TemporaryDirectory() as tmp:
            service = ProviderAnimationService(
                Path(tmp) / "animation.json", provider="bishop"
            )
            with self.assertRaises(AnimationError):
                service.propose(bad, actor="creator", intent_reference="user prompt")
        leaked = pattern()
        leaked["behavior"]["example"] = "/project/screenshot.png"
        with tempfile.TemporaryDirectory() as tmp:
            service = ProviderAnimationService(
                Path(tmp) / "animation.json", provider="bishop"
            )
            with self.assertRaises(AnimationError):
                service.propose(leaked, actor="creator", intent_reference="user prompt")

    def test_intent_only_creates_proposal_and_explicit_decision_promotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "animation.json"
            service = ProviderAnimationService(
                path, provider="bishop", clock=lambda: "2026-08-13T00:00:00Z"
            )
            proposal = service.propose(
                pattern(), actor="creator", intent_reference="C01+C02 are awesome"
            )
            self.assertFalse(path.exists())
            event = service.decide(
                Path(proposal["path"]),
                decision="approved",
                actor="creator",
                reason="sanitized abstraction approved",
            )
            catalog = service.load()
            self.assertEqual(event["type"], "promotion-approved")
            self.assertEqual(
                catalog["patterns"][0]["promotionEventId"], event["eventId"]
            )

    def test_rejection_records_event_without_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ProviderAnimationService(
                Path(tmp) / "animation.json", provider="bishop"
            )
            proposal = service.propose(
                pattern(), actor="creator", intent_reference="intent"
            )
            event = service.decide(
                Path(proposal["path"]),
                decision="rejected",
                actor="creator",
                reason="not generic",
            )
            self.assertEqual(event["type"], "promotion-rejected")
            self.assertEqual(service.load()["patterns"], [])
