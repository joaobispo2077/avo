from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


from avo import transcribe


class FakeWord:
    def __init__(self, word: str, start: float, end: float, probability: float):
        self.word, self.start, self.end = word, start, end
        self.probability = probability


class FakeSegment:
    words = [
        FakeWord(" Olá,", 0.1, 0.5, 0.98),
        FakeWord(" mundo!", 0.6, 1.0, 0.97),
    ]


class FakeWhisperModel:
    init_args = None
    transcribe_args = None

    def __init__(self, model_path: str, **kwargs):
        FakeWhisperModel.init_args = (model_path, kwargs)

    def transcribe(self, media: str, **kwargs):
        FakeWhisperModel.transcribe_args = (media, kwargs)
        return iter([FakeSegment()]), types.SimpleNamespace(language="pt")


class TranscribeTests(unittest.TestCase):
    def make_model(self, root: Path) -> Path:
        model_dir = root / "small"
        model_dir.mkdir()
        for name in transcribe.MODEL_FILES:
            (model_dir / name).write_text(name)
        return model_dir

    def test_runtime_is_offline_and_forces_portuguese(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = self.make_model(root)
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = FakeWhisperModel
            with patch.dict(sys.modules, {"faster_whisper": fake_module}):
                runtime = transcribe.LocalTranscriber(model_dir=model_dir)
                video = root / "clip.mp4"
                video.write_bytes(b"media")
                payload = runtime.transcribe(
                    video, transcribe.source_fingerprint(video)
                )

            _, init_options = FakeWhisperModel.init_args
            self.assertTrue(init_options["local_files_only"])
            _, options = FakeWhisperModel.transcribe_args
            self.assertEqual(options["language"], "pt")
            self.assertEqual(options["task"], "transcribe")
            self.assertTrue(options["word_timestamps"])
            self.assertTrue(options["vad_filter"])
            self.assertEqual(payload["text"], "Olá, mundo!")

    def test_missing_model_names_preparation_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "avo.prepare_transcription"):
                transcribe.LocalTranscriber(model_dir=Path(tmp) / "missing")

    def test_empty_inference_is_valid(self) -> None:
        fingerprint = {
            "path": "/tmp/empty.mp4",
            "size_bytes": 0,
            "mtime_ns": 0,
            "sha256": "0" * 64,
        }
        payload = transcribe.build_transcript_payload([], fingerprint, "small", "test")
        self.assertEqual(payload["words"], [])


if __name__ == "__main__":
    unittest.main()
