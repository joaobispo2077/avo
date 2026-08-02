from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class AdapterBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT))
        from avo.adapters.base import parse_routing_token, routing_token_for_job

        self.parse = parse_routing_token
        self.routing_token = routing_token_for_job

    def test_parse_routing_token(self) -> None:
        self.assertEqual(self.parse("video-use+faster-whisper"), ("video-use", "faster-whisper"))
        self.assertEqual(self.parse("elevenlabs"), ("elevenlabs", "elevenlabs"))

    def test_routing_token_transcribe_local(self) -> None:
        config = json.loads((ROOT / "config" / "avo.config.json").read_text(encoding="utf-8"))
        token = self.routing_token(config, "transcribe", "local")
        self.assertEqual(token, "video-use+faster-whisper")


class AdapterTranscribeTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT))

    @mock.patch("subprocess.run")
    def test_faster_whisper_invokes_subprocess(self, run: mock.Mock) -> None:
        run.return_value = mock.Mock(returncode=0, stdout="ok", stderr="")
        from avo.adapters.transcribe.faster_whisper import FasterWhisperAdapter
        from avo.adapters.base import JobRequest

        result = FasterWhisperAdapter().run(
            JobRequest(job="transcribe", label="local", argv=["video.mp4"], root=ROOT)
        )
        self.assertEqual(result.exit_code, 0)
        cmd = run.call_args[0][0]
        self.assertTrue(str(cmd[1]).endswith("transcribe.py"))
        self.assertIn("--model", cmd)
        self.assertIn("models_used", result.__dict__)
        self.assertIn("transcribe", result.models_used)

    def test_elevenlabs_stub_without_key(self) -> None:
        from avo.adapters.transcribe.elevenlabs import ElevenLabsAdapter
        from avo.adapters.base import JobRequest

        with mock.patch.dict("os.environ", {}, clear=True):
            result = ElevenLabsAdapter().run(
                JobRequest(job="transcribe", label="paid", argv=[], root=ROOT, env={})
            )
        self.assertEqual(result.exit_code, 2)
        self.assertIn("ELEVENLABS_API_KEY", result.stderr)


class RunJobCliTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT))

    @mock.patch("avo.adapters.run_job.resolve_adapter")
    def test_run_job_success_json(self, resolve: mock.Mock) -> None:
        from avo.adapters.base import JobResult

        adapter = mock.Mock()
        adapter.routing_id = "faster-whisper"
        adapter.run.return_value = JobResult(exit_code=0, stdout="", stderr="")
        resolve.return_value = adapter
        from avo.adapters import run_job

        code = run_job.main(["transcribe", "--label", "local", "--root", str(ROOT), "--"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
