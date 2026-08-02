from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

from avo import transcribe


class FakeRuntime:
    def __init__(self, model: str = "small", error: str | None = None):
        self.model = model
        self.error = error
        self.calls = 0

    def transcribe(self, video: Path, fingerprint: dict):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        segment = SimpleNamespace(
            words=[SimpleNamespace(word=" Olá", start=0.1, end=0.5, probability=0.9)]
        )
        return transcribe.build_transcript_payload(
            [segment], fingerprint, self.model, "test"
        )


class CacheTests(unittest.TestCase):
    def test_reuses_matching_cache_and_force_bypasses_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"one")
            edit = root / "edit"
            first = FakeRuntime()
            transcribe.transcribe_one(video, edit, runtime=first, verbose=False)
            second = FakeRuntime()
            transcribe.transcribe_one(video, edit, runtime=second, verbose=False)
            self.assertEqual(second.calls, 0)
            transcribe.transcribe_one(
                video, edit, runtime=second, force=True, verbose=False
            )
            self.assertEqual(second.calls, 1)

    def test_source_or_model_change_regenerates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"one")
            edit = root / "edit"
            transcribe.transcribe_one(
                video, edit, runtime=FakeRuntime(), verbose=False
            )
            video.write_bytes(b"two")
            changed = FakeRuntime()
            transcribe.transcribe_one(video, edit, runtime=changed, verbose=False)
            self.assertEqual(changed.calls, 1)
            medium = FakeRuntime("medium")
            transcribe.transcribe_one(
                video, edit, runtime=medium, model="medium", verbose=False
            )
            self.assertEqual(medium.calls, 1)

    def test_legacy_cache_regenerates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"one")
            edit = root / "edit"
            out = transcribe.transcript_path(video, edit)
            out.parent.mkdir(parents=True)
            out.write_text(json.dumps({"words": []}))
            runtime = FakeRuntime()
            transcribe.transcribe_one(video, edit, runtime=runtime, verbose=False)
            self.assertEqual(runtime.calls, 1)
            self.assertEqual(json.loads(out.read_text())["engine"], "faster-whisper")

    def test_failed_refresh_preserves_previous_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"one")
            edit = root / "edit"
            out = transcribe.transcribe_one(
                video, edit, runtime=FakeRuntime(), verbose=False
            )
            original = out.read_bytes()
            video.write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                transcribe.transcribe_one(
                    video,
                    edit,
                    runtime=FakeRuntime(error="inference failed"),
                    verbose=False,
                )
            self.assertEqual(out.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
