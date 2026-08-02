from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


from avo import prepare_transcription


class PrepareTranscriptionTests(unittest.TestCase):
    def test_downloads_to_explicit_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "small"
            calls = []

            def downloader(model: str, output_dir: str) -> str:
                target = Path(output_dir)
                target.mkdir(parents=True, exist_ok=True)
                for name in ("config.json", "model.bin", "tokenizer.json"):
                    (target / name).write_text(name)
                calls.append((model, target))
                return str(target)

            result = prepare_transcription.prepare_model(
                "small", destination, downloader=downloader
            )
            self.assertEqual(result, destination.resolve())
            self.assertEqual(calls, [("small", destination.resolve())])

    def test_reuses_prepared_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            for name in ("config.json", "model.bin", "tokenizer.json"):
                (destination / name).write_text(name)
            result = prepare_transcription.prepare_model(
                "small",
                destination,
                downloader=lambda *_args, **_kwargs: self.fail("download called"),
            )
            self.assertEqual(result, destination.resolve())

    def test_rejects_english_only_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "multilingual"):
            prepare_transcription.prepare_model("small.en", Path("/tmp/model"))

    def test_surfaces_download_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def fail(*_args, **_kwargs):
                raise OSError("network unavailable")

            with self.assertRaisesRegex(RuntimeError, "network unavailable"):
                prepare_transcription.prepare_model(
                    "small", Path(tmp) / "model", downloader=fail
                )


if __name__ == "__main__":
    unittest.main()
