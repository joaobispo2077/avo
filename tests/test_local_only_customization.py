from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# AVO keeps *runtime* transcription local: the Python helpers must not call a
# hosted transcription service or embed provider credentials. Product docs
# (README, docs/install/README.md) may legitimately name Paid alternatives such as
# ElevenLabs in the tool-routing table — those are documentation, not runtime
# code, so they are intentionally out of scope for this guarantee.
RUNTIME_FILES = [
    ROOT / "src/avo/transcribe.py",
    ROOT / "src/avo/transcribe_batch.py",
    ROOT / "src/avo/prepare_transcription.py",
    ROOT / "src/avo/build_captions.py",
    ROOT / "src/avo/generate_sfx.py",
    ROOT / "src/avo/final_transcript_artifacts.py",
    ROOT / "src/avo/render.py",
    ROOT / "src/avo/validate_edl.py",
]

# Tokens that would indicate a hosted transcription call or a leaked credential
# inside runtime helper code.
FORBIDDEN_IN_RUNTIME = [
    "ELEVENLABS_API_KEY",
    "api.elevenlabs.io",
    "xi-api-key",
    "OPENAI_API_KEY",
]


class RuntimeStaysLocalTests(unittest.TestCase):
    def test_runtime_helpers_have_no_hosted_transcription_or_keys(self) -> None:
        for path in RUNTIME_FILES:
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            for token in FORBIDDEN_IN_RUNTIME:
                self.assertNotIn(
                    token, content, f"{token} must not appear in runtime helper {path.name}"
                )


if __name__ == "__main__":
    unittest.main()
