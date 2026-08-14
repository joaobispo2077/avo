from __future__ import annotations
import unittest
from avo.timeline.lineage import rebase_bmap
class BMapIntegrationTests(unittest.TestCase):
    def test_rebase_marks_ambiguous_for_human(self):
        cues=[{"cueId":"q","rawAnchorRanges":[[100,200]]}]
        result=rebase_bmap(cues,{"q":[[100,200],[300,400]]})
        self.assertEqual(result[0]["rebaseState"],"ambiguous")
        self.assertEqual(result[0]["reviewState"],"needs-human-judgment")
