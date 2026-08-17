from __future__ import annotations

import unittest

from avo.timeline.sync import ConstantOffset


class OffsetTests(unittest.TestCase):
    def test_audio_plus_128_ms(self):
        transform = ConstantOffset(offset_ticks=128, timebase_num=1, timebase_den=1000)
        self.assertEqual(transform.audio_to_picture(1000), 1128)
        self.assertEqual(transform.picture_to_audio(1128), 1000)
