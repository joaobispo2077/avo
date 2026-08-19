from __future__ import annotations

import unittest

from avo.timeline.sync import SyncError, validate_raw_sync_basis


class SyncLineageTests(unittest.TestCase):
    def test_rejects_corrected_sources(self):
        with self.assertRaises(SyncError):
            validate_raw_sync_basis({"kind": "corrected-delivery"}, {"kind": "raw"})

    def test_accepts_raw(self):
        validate_raw_sync_basis({"kind": "raw"}, {"kind": "raw"})
