from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from avo.adapters.understand.watch_policy import WatchPolicyError, resolve_watch_policy


class WatchPolicyTests(unittest.TestCase):
    def test_defaults_inherit_transcription_and_omit_context(self) -> None:
        policy = resolve_watch_policy(transcription_model="small")
        self.assertEqual(policy.whisper_model, "small")
        self.assertEqual(policy.device, "auto")
        self.assertEqual(policy.max_frames, 18)
        self.assertEqual(policy.context, {})
        self.assertEqual(policy.sources["whisperModel"], "default")

    def test_full_precedence_and_array_replacement(self) -> None:
        policy = resolve_watch_policy(
            transcription_model="small",
            scopes=[
                ("global", {"device": "cpu", "acceptanceCriteria": ["global"]}),
                ("provider", {"device": "cuda"}),
                ("registry", {"language": "en", "acceptanceCriteria": ["registry"]}),
                ("project", {"format": "documentary"}),
                ("invocation", {"device": "cuda:2", "acceptanceCriteria": ["cli"]}),
            ],
        )
        self.assertEqual(policy.device, "cuda:2")
        self.assertEqual(policy.context["language"], "en")
        self.assertEqual(policy.context["format"], "documentary")
        self.assertEqual(policy.context["acceptanceCriteria"], ["cli"])
        self.assertEqual(policy.sources["device"], "invocation")

    def test_validation_and_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp).resolve()
            policy = resolve_watch_policy(
                transcription_model="medium",
                raw_dir=raw,
                scopes=[("project", {"workingDirectory": "edit/watch"})],
            )
            self.assertEqual(policy.working_directory, raw / "edit" / "watch")
            payload = policy.payload(redact_working_directory=True)
            self.assertEqual(
                payload["effective"]["workingDirectory"], "<rawDir>/edit/watch"
            )
            self.assertEqual(payload["effective"]["repairMaxFrames"], 8)
        for invalid in (
            {"device": "metal"},
            {"maxFrames": 0},
            {"repairMaxFrames": 19, "maxFrames": 18},
            {"analysisAttempts": 4},
            {"toolAttempts": 0},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(WatchPolicyError):
                resolve_watch_policy(scopes=[("project", invalid)])

    def test_unrelated_resolutions_do_not_leak(self) -> None:
        first = resolve_watch_policy(
            scopes=[("project", {"language": "pt-BR", "device": "cpu"})]
        )
        second = resolve_watch_policy(
            scopes=[("project", {"language": "ja", "device": "cuda"})]
        )
        self.assertEqual(first.context["language"], "pt-BR")
        self.assertEqual(second.context["language"], "ja")
        self.assertNotEqual(first.policy_hash, second.policy_hash)


if __name__ == "__main__":
    unittest.main()
