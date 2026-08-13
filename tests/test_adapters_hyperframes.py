from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from avo.adapters.motion.hyperframes import (
    HyperframesAdapter, HyperframesError, build_composition_spec, compile_project,
)


def asset(path: Path, muted: bool) -> dict:
    path.write_bytes(path.name.encode())
    return {"path": str(path), "hash": hashlib.sha256(path.read_bytes()).hexdigest(), "durationSec": 2, "muted": muted}


PHRASES = [{
    "id": "phrase-1", "startSec": 0, "endSec": 1.8, "renderedText": "Switch OLED",
    "words": [
        {"id": "p1-w1", "text": "Switch", "startSec": 0, "endSec": .7, "punch": False, "highlightEnterSec": 0, "highlightExitSec": .7},
        {"id": "p1-w2", "text": "OLED", "startSec": .7, "endSec": 1.4, "punch": True, "highlightEnterSec": .7, "highlightExitSec": 1.4},
    ], "autofixes": [],
}]


class HyperframesAdapterTests(unittest.TestCase):
    def test_compiler_emits_direct_root_muted_video_separate_audio_and_local_runtime(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            root = Path(tmp)
            assets = {"baseVideo": asset(root / "video.mp4", True), "dialogueAudio": asset(root / "audio.m4a", False)}
            item = {
                "id": "01", "editedDurationSec": 2, "captions": PHRASES,
                "layout": {"mode": "full-frame", "captionAnchor": "bottom"},
                "factualReviewReferences": ["review:1"],
            }
            spec = build_composition_spec(
                batch_id="batch", item=item, output={"width": 1080, "height": 1920, "fps": 30},
                assets=assets, proof_revision=1, expected_output_path=root / "proof.mp4",
            )
            project = compile_project(spec, root / "project")
            page = (project / "index.html").read_text(encoding="utf-8")
            self.assertIn('src="assets/gsap.min.js"', page)
            self.assertNotIn("https://", page)
            self.assertRegex(page, r'<main[\s\S]*?<video[^>]+id="base-video"')
            self.assertIn("muted", page)
            self.assertIn('<audio\n        id="dialogue-audio"', page)
            self.assertEqual(page.count("gsap.timeline({ paused: true })"), 1)
            self.assertEqual((project / "runtime.js").read_text().count("gsap.timeline"), 0)
            self.assertNotIn("COMPARATIVO SEM HYPE", page)
            self.assertNotIn("GAMEPLAY ILUSTRATIVA", page)

    def test_split_geometry_requires_two_complete_regions(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            root = Path(tmp)
            assets = {"baseVideo": asset(root / "v.mp4", True), "dialogueAudio": asset(root / "a.m4a", False)}
            item = {"id": "01", "editedDurationSec": 2, "captions": [], "layout": {"mode": "split", "captionAnchor": "seam", "splitRatio": .5}}
            with self.assertRaises(Exception):
                build_composition_spec(batch_id="b", item=item, output={"width": 1080, "height": 1920, "fps": 30}, assets=assets, proof_revision=1, expected_output_path=root / "x.mp4")

    def test_subprocess_adapter_adds_strict_and_propagates_failure(self) -> None:
        calls = []
        def runner(argv, **kwargs):
            calls.append((list(argv), kwargs))
            return subprocess.CompletedProcess(argv, 7, "out", "bad composition")
        result = HyperframesAdapter(runner=runner).execute("check", Path("/tmp/project"), root=Path.cwd())
        self.assertEqual(result.exit_code, 7)
        self.assertIn("--strict", calls[0][0])
        self.assertEqual(result.stderr, "bad composition")


if __name__ == "__main__":
    unittest.main()
