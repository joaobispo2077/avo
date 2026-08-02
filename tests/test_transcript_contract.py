from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

from avo import pack_transcripts
from avo import render
from avo import transcribe


class TranscriptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads(
            (ROOT / "tests/fixtures/transcript_ptbr.json").read_text(encoding="utf-8")
        )

    def test_fixture_is_valid_and_ordered(self) -> None:
        transcribe.validate_transcript_payload(self.fixture)
        starts = [word["start"] for word in self.fixture["words"]]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(all(word["speaker_id"] is None for word in self.fixture["words"]))

    def test_existing_consumers_accept_local_words(self) -> None:
        phrases = pack_transcripts.group_into_phrases(self.fixture["words"])
        selected = render._words_in_range(self.fixture, 0.0, 1.2)
        self.assertEqual(len(phrases), 1)
        self.assertEqual(
            [word["text"] for word in selected], ["Olá,", "este", "é", "um"]
        )

    def test_adapter_preserves_punctuation(self) -> None:
        segment = SimpleNamespace(
            words=[SimpleNamespace(word=" Olá!", start=0.0, end=0.4, probability=0.9)]
        )
        payload = transcribe.build_transcript_payload(
            [segment], dict(self.fixture["source"]), "small", "test"
        )
        self.assertEqual(payload["words"][0]["text"], "Olá!")
        self.assertEqual(payload["words"][0]["probability"], 0.9)


if __name__ == "__main__":
    unittest.main()
