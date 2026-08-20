from __future__ import annotations

import unittest

from avo.timeline.tracks import inspect_visual_hierarchy


class VideoTests(unittest.TestCase):
    def test_overlay_requires_face_avoidance(self):
        self.assertIn(
            "face-avoidance",
            inspect_visual_hierarchy(
                [{"role": "overlay", "faceAvoidance": False, "safeZones": []}]
            ),
        )
