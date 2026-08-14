from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from avo.adapters.base import JobRequest, JobResult
from avo.adapters.understand.watch_skill import WatchSkillAdapter


class WatchAdapterTests(unittest.TestCase):
    def test_invokes_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = mock.Mock(returncode=0, stdout="# report", stderr="")
            with mock.patch("subprocess.run", return_value=completed) as run:
                result = WatchSkillAdapter(executable="watch-skill").run(
                    JobRequest(
                        job="understand",
                        label="review",
                        argv=["watch", "proof.mp4", "review"],
                        root=Path(tmp),
                    )
                )
            self.assertEqual(result.exit_code, 0)
            self.assertIn("watch", run.call_args.args[0])

    def test_structured_review_uses_real_watch_command_and_pins_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            adapter = WatchSkillAdapter(executable="watch-skill")
            with mock.patch.object(
                adapter,
                "run",
                side_effect=[
                    JobResult(
                        exit_code=0,
                        stdout="# watch-skill: video report\n> **Indexed:** video_id `vid-1`",
                    ),
                    JobResult(
                        exit_code=0,
                        stdout=(
                            "{\"status\":\"pass\",\"confidence\":0.91,"
                            "\"findings\":[]}\n(confidence: 0.91)"
                        ),
                    ),
                    JobResult(exit_code=0, stdout="0.6.0\n"),
                ],
            ) as run:
                result = adapter.review(
                    candidate,
                    checkpoint="cut-proof",
                    scope="full",
                    windows=[{"start": 1.0, "end": 2.0, "reason": "join"}],
                    artifact_dir=root / "review",
                )
            watch_argv = run.call_args_list[0].args[0].argv
            ask_argv = run.call_args_list[1].args[0].argv
            self.assertEqual(watch_argv[0], "watch")
            self.assertIn("--index", watch_argv)
            self.assertIn("--timestamps", watch_argv)
            self.assertEqual(ask_argv[:2], ["ask", "vid-1"])
            self.assertIn("--no-cache", ask_argv)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["coverage"]["windows"][0]["reason"], "join")
            self.assertTrue((root / "review" / "watch-evidence.json").is_file())
            self.assertTrue((root / "review" / "watch-analysis.txt").is_file())


    def test_malformed_analysis_blocks_instead_of_empty_pass(self):
        from avo.timeline.ports import ToolError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            adapter = WatchSkillAdapter(executable="watch-skill")
            with mock.patch.object(
                adapter,
                "run",
                side_effect=[
                    JobResult(exit_code=0, stdout="video_id `vid-1`"),
                    JobResult(exit_code=0, stdout="looks fine"),
                ],
            ):
                with self.assertRaises(ToolError) as raised:
                    adapter.review(candidate, scope="full", artifact_dir=root / "review")
            self.assertEqual(raised.exception.code, "WATCH_MALFORMED")

    def test_empty_windows_rejected_for_targeted_review(self):
        with self.assertRaises(ValueError):
            WatchSkillAdapter.validate_coverage("targeted", [])
