from __future__ import annotations
import unittest
from avo.timeline.sync import LinearDrift,PiecewiseTransform,validate_residuals,SyncError
class DriftTests(unittest.TestCase):
 def test_linear(self):
  t=LinearDrift.from_points((0,100),(10000,120))
  self.assertEqual(t.offset_at(5000),110)
 def test_piecewise(self):
  t=PiecewiseTransform([(0,100),(1000,110),(2000,130)])
  self.assertEqual(t.offset_at(1500),120)
 def test_residual_failure(self):
  with self.assertRaises(SyncError):validate_residuals([10,50],40)
