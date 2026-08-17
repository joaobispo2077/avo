from __future__ import annotations

import unittest

from avo.timeline.animation import promote_pattern, recommend_patterns


class AnimationIntegrationTests(unittest.TestCase):
    def test_bishop_reference_reuses_behavior_only(self):
        source = {
            "patternId": "bishop-c01-c02",
            "name": "Chapter pair",
            "behavior": {"sequence": ["chapter-ident", "topic-card"]},
            "contexts": ["talking-head-review"],
            "exclusions": ["evidence-fullscreen"],
            "requiredAssets": [],
            "accessibility": {"reducedMotion": True},
            "exemplars": [{"candidateHash": "a" * 64, "section": "C01+C02"}],
        }
        promoted = promote_pattern(
            source, actor="creator", approval_reference="approved"
        )
        self.assertEqual(
            recommend_patterns(
                [promoted], {"format": "talking-head-review", "constraints": []}
            )[0]["patternId"],
            "bishop-c01-c02",
        )
