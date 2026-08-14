from __future__ import annotations
import unittest
from avo.timeline.review import classify_findings
class BlockerTests(unittest.TestCase):
 def test_policy_and_meaning_need_human(self):
  self.assertEqual(classify_findings([{"classification":"meaning"}]),"needs-human-judgment")
 def test_tool_error_blocks(self):self.assertEqual(classify_findings([{"classification":"tool-error"}]),"blocked")
