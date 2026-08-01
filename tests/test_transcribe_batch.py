from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import transcribe
import transcribe_batch


class FakeRuntime:
    def __init__(self, model="small"):
        self.model = model
        self.calls = []

    def transcribe(self, video: Path, fingerprint: dict):
        self.calls.append(video.name)
        segment = SimpleNamespace(
            words=[SimpleNamespace(word=" Oi", start=0.0, end=0.2, probability=0.9)]
        )
        return transcribe.build_transcript_payload(
            [segment], fingerprint, self.model, "test"
        )


class BatchTests(unittest.TestCase):
    def make_videos(self, root: Path) -> None:
        (root / "a.mp4").write_bytes(b"a")
        (root / "b.mov").write_bytes(b"b")

    def test_uses_one_shared_runtime_for_pending_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_videos(root)
            created = []

            def factory(**kwargs):
                runtime = FakeRuntime(kwargs["model"])
                created.append((runtime, kwargs))
                return runtime

            result = transcribe_batch.transcribe_directory(
                root, root / "edit", runtime_factory=factory, verbose=False
            )
            self.assertEqual(result.failures, [])
            self.assertEqual(len(created), 1)
            self.assertEqual(sorted(created[0][0].calls), ["a.mp4", "b.mov"])
            self.assertEqual(created[0][1]["num_workers"], 1)

    def test_all_cached_batch_does_not_load_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_videos(root)
            edit = root / "edit"
            runtime = FakeRuntime()
            for video in transcribe_batch.find_videos(root):
                transcribe.transcribe_one(
                    video, edit, runtime=runtime, verbose=False
                )
            result = transcribe_batch.transcribe_directory(
                root,
                edit,
                runtime_factory=lambda **_kwargs: self.fail("runtime loaded"),
                verbose=False,
            )
            self.assertEqual(result.cached, 2)
            self.assertEqual(result.transcribed, 0)

    def test_rejects_zero_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "at least 1"):
                transcribe_batch.transcribe_directory(
                    Path(tmp), Path(tmp) / "edit", workers=0
                )


if __name__ == "__main__":
    unittest.main()
