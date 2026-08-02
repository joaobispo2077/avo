from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class TranscribeEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        from avo import transcribe

        self.transcribe = transcribe

    def tearDown(self) -> None:
        for key in ("AVO_MODEL_DIR", "VIDEO_USE_MODEL_DIR"):
            os.environ.pop(key, None)

    def test_avo_model_dir_preferred(self) -> None:
        os.environ["AVO_MODEL_DIR"] = "/tmp/avo-models"
        os.environ["VIDEO_USE_MODEL_DIR"] = "/tmp/legacy-models"
        self.assertEqual(
            self.transcribe.default_model_root(),
            Path("/tmp/avo-models").resolve(),
        )

    def test_video_use_model_dir_fallback(self) -> None:
        os.environ["VIDEO_USE_MODEL_DIR"] = "/tmp/legacy-models"
        self.assertEqual(
            self.transcribe.default_model_root(),
            Path("/tmp/legacy-models").resolve(),
        )


if __name__ == "__main__":
    unittest.main()
