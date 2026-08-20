from __future__ import annotations

import unittest
import unittest.mock

from avo import shorts_qc


class ShortsQcTests(unittest.TestCase):
    def test_probe_profile_and_caption_bounds_gate(self) -> None:
        item = {"editedDurationSec": 2, "captions": []}
        good = {
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "2.0"},
        }
        self.assertEqual(shorts_qc.evaluate_item(item, good)["status"], "passed")
        bad = {
            "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
            "format": {"duration": "3.0"},
        }
        self.assertEqual(shorts_qc.evaluate_item(item, bad)["status"], "failed")

    def test_insertion_requires_watch_semantic_review(self) -> None:
        item = {"editedDurationSec": 2, "captions": [], "insertion": {"id": "gameplay"}}
        probe = {
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "2.0"},
        }
        report = shorts_qc.evaluate_item(item, probe)
        self.assertIn(
            "watch-review-required", [finding["code"] for finding in report["findings"]]
        )
        self.assertEqual(
            shorts_qc.evaluate_item(item, probe, watch_reference="watch://approved")[
                "status"
            ],
            "passed",
        )

    def test_qc_honors_plan_output_geometry(self) -> None:
        item = {"editedDurationSec": 2, "captions": []}
        probe = {
            "streams": [
                {"codec_type": "video", "width": 720, "height": 1280},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "2.0"},
        }
        failed = shorts_qc.evaluate_item(
            item, probe, output={"width": 1080, "height": 1920}
        )
        self.assertEqual(failed["status"], "failed")
        passed = shorts_qc.evaluate_item(
            item, probe, output={"width": 720, "height": 1280}
        )
        self.assertEqual(passed["status"], "passed")

    def test_qc_proof_artifact_applies_video_metrics(self) -> None:
        item = {"editedDurationSec": 2, "captions": []}
        artifact = {"path": "proof.mp4"}
        probe = {
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "2.0"},
        }
        with (
            unittest.mock.patch.object(
                shorts_qc.shorts_media, "probe_media", return_value=probe
            ),
            unittest.mock.patch.object(
                shorts_qc.shorts_media,
                "analyze_video_metrics",
                return_value={
                    "blackFrames": 1,
                    "freezeSeconds": 0,
                    "integratedLufs": -16,
                },
            ),
        ):
            report = shorts_qc.qc_proof_artifact(item, artifact, collect_metrics=True)
        codes = [finding["code"] for finding in report["findings"]]
        self.assertIn("black-frames", codes)


if __name__ == "__main__":
    unittest.main()
