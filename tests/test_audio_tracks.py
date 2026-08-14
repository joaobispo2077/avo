from __future__ import annotations
import unittest
from avo.timeline.tracks import inspect_audio_hierarchy
class AudioTests(unittest.TestCase):
 def test_dialogue_not_centered_fails(self):
  findings=inspect_audio_hierarchy([{"role":"dialogue","channels":[0],"gainDb":0},{"role":"music","gainDb":0}])
  self.assertIn("dialogue-channel-mapping",findings);self.assertIn("music-masks-dialogue",findings)
