from __future__ import annotations

import unittest

from avo.timeline.sync import build_constant_offset_snapshot, validate_sync_snapshot


class SyncIntegrationTests(unittest.TestCase):
    def test_calibration_and_full_program_qc(self):
        s = build_constant_offset_snapshot(
            picture={
                "sourceId": "cam",
                "kind": "raw",
                "fingerprint": {"sha256": "a" * 64, "sizeBytes": 1},
                "stream": "v:0",
            },
            audio={
                "sourceId": "mic",
                "kind": "raw",
                "fingerprint": {"sha256": "b" * 64, "sizeBytes": 1},
                "stream": "a:0",
                "channels": [0],
            },
            offset_ticks=128,
            timebase={"num": 1, "den": 1000},
            samples=[(0, -128), (10000, 9872)],
            tolerance_ticks=40,
        )
        validate_sync_snapshot(s)
        self.assertEqual(s["fullProgramValidation"]["status"], "pass")
