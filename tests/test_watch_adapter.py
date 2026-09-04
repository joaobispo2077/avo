from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from avo.adapters.base import JobRequest, JobResult
from avo.adapters.understand.watch_skill import WatchSkillAdapter, _extract_json_object
from avo.timeline.ports import ToolError

_RESOLVE = "avo.models.resolve_option_id"


class WatchAdapterTests(unittest.TestCase):
    def test_last_schema_valid_object_wins(self):
        result = _extract_json_object(
            '{"status":"fail","findings":[]} noise '
            '{"status":"pass","confidence":1,"findings":[]}'
        )
        self.assertEqual(result["status"], "pass")

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
                            '{"status":"pass","confidence":0.91,'
                            '"findings":[]}\n(confidence: 0.91)'
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
            self.assertIn("--whisper-model", watch_argv)
            self.assertIn("--timestamps", watch_argv)
            self.assertEqual(ask_argv[:2], ["ask", "vid-1"])
            self.assertIn("--no-cache", ask_argv)
            self.assertIn("--max-frames", ask_argv)
            self.assertNotIn("required windows=", ask_argv[2])
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["coverage"]["windows"][0]["reason"], "join")
            self.assertTrue((root / "review" / "watch-evidence.json").is_file())
            self.assertTrue((root / "review" / "watch-analysis.txt").is_file())

    def test_policy_controls_prompt_frames_model_root_and_cpu_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            work = root / "watch-work"
            adapter = WatchSkillAdapter(executable="watch-skill")
            policy = {
                "effective": {
                    "whisperModel": "small",
                    "device": "cpu",
                    "maxFrames": 11,
                    "repairMaxFrames": 4,
                    "analysisAttempts": 2,
                    "toolAttempts": 2,
                    "workingDirectory": str(work),
                },
                "sources": {"device": "invocation"},
                "policyHash": "a" * 64,
            }
            with mock.patch.object(
                adapter,
                "run",
                side_effect=[
                    JobResult(exit_code=0, stdout="video_id `v-1`"),
                    JobResult(exit_code=0, stdout='{"status":"pass","findings":[]}'),
                    JobResult(exit_code=0, stdout="1.0"),
                ],
            ) as run:
                result = adapter.review(
                    candidate,
                    policy=policy,
                    context={"format": "tutorial", "language": "en"},
                    artifact_dir=root / "review",
                )
            watch_request = run.call_args_list[0].args[0]
            ask_request = run.call_args_list[1].args[0]
            self.assertEqual(watch_request.root, work)
            self.assertEqual(watch_request.env["CUDA_VISIBLE_DEVICES"], "-1")
            self.assertEqual(
                watch_request.argv[watch_request.argv.index("--whisper-model") + 1],
                "small",
            )
            self.assertEqual(
                ask_request.argv[ask_request.argv.index("--max-frames") + 1], "11"
            )
            self.assertIn("Declared format: tutorial", ask_request.argv[2])
            self.assertIn("Declared language: en", ask_request.argv[2])
            self.assertNotIn("talking-head", ask_request.argv[2])
            self.assertNotIn("Nintendo", ask_request.argv[2])
            self.assertEqual(result["policy"]["policyHash"], "a" * 64)
            self.assertEqual(result["outcomeKind"], "content")
            self.assertEqual(len(result["attempts"]), 1)

    def test_auto_device_does_not_force_cpu_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            adapter = WatchSkillAdapter(executable="watch-skill")
            with mock.patch.object(
                adapter,
                "run",
                side_effect=[
                    JobResult(exit_code=0, stdout="video_id `v-1`"),
                    JobResult(exit_code=0, stdout='{"status":"pass","findings":[]}'),
                    JobResult(exit_code=0, stdout="1.0"),
                ],
            ) as run:
                adapter.review(candidate, artifact_dir=root / "review")
            self.assertNotIn("CUDA_VISIBLE_DEVICES", run.call_args_list[0].args[0].env)

    def test_malformed_analysis_blocks_instead_of_empty_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            adapter = WatchSkillAdapter(executable="watch-skill")
            with (
                mock.patch.object(
                    adapter,
                    "run",
                    side_effect=[
                        JobResult(exit_code=0, stdout="video_id `vid-1`"),
                        JobResult(exit_code=0, stdout="looks fine"),
                        JobResult(exit_code=0, stdout="still not json"),
                    ],
                ),
                self.assertRaises(ToolError) as raised,
            ):
                adapter.review(candidate, scope="full", artifact_dir=root / "review")
            self.assertEqual(raised.exception.code, "WATCH_MALFORMED")

    def test_retry_uses_repair_prompt_and_reduced_frame_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            adapter = WatchSkillAdapter(executable="watch-skill")
            policy = {
                "effective": {
                    "maxFrames": 12,
                    "repairMaxFrames": 3,
                    "analysisAttempts": 2,
                }
            }
            with mock.patch.object(
                adapter,
                "run",
                side_effect=[
                    JobResult(exit_code=0, stdout="video_id `vid-1`"),
                    JobResult(exit_code=0, stdout="not structured"),
                    JobResult(
                        exit_code=0,
                        stdout='{"status":"pass","confidence":1,"findings":[]}',
                    ),
                    JobResult(exit_code=0, stdout="1.0"),
                ],
            ) as run:
                result = adapter.review(
                    candidate, policy=policy, artifact_dir=root / "review"
                )
            first_ask = run.call_args_list[1].args[0].argv
            repair_ask = run.call_args_list[2].args[0].argv
            self.assertEqual(first_ask[-1], "12")
            self.assertEqual(repair_ask[-1], "3")
            self.assertIn("Repair the prior answer", repair_ask[2])
            self.assertEqual(len(result["attempts"]), 2)

    def test_ignores_echoed_window_json_without_analysis_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            adapter = WatchSkillAdapter(executable="watch-skill")
            echoed = (
                "The video does not clearly show an answer to: windows="
                '[{"start": 33.53, "end": 34.03, "reason": "join"}]. '
                "No guess is being made."
            )
            with mock.patch.object(
                adapter,
                "run",
                side_effect=[
                    JobResult(exit_code=0, stdout="video_id `vid-1`"),
                    JobResult(exit_code=0, stdout=echoed),
                    JobResult(exit_code=0, stdout="0.6.0\n"),
                ],
            ):
                result = adapter.review(
                    candidate, scope="full", artifact_dir=root / "review"
                )
            self.assertEqual(result["status"], "needs-human-judgment")
            self.assertEqual(result["findings"][0]["classification"], "meaning")

    def test_picks_analysis_json_when_window_objects_are_echoed(self):
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
                    JobResult(
                        exit_code=0,
                        stdout=(
                            '{"start":1.0,"end":2.0,"reason":"join"} '
                            '{"status":"fail","confidence":0.4,'
                            '"findings":[{"classification":"technical",'
                            '"message":"flash at join"}]}'
                        ),
                    ),
                    JobResult(exit_code=0, stdout="0.6.0\n"),
                ],
            ):
                result = adapter.review(
                    candidate, scope="full", artifact_dir=root / "review"
                )
            self.assertEqual(result["status"], "fail")

    def test_empty_windows_rejected_for_targeted_review(self):
        with self.assertRaises(ValueError):
            WatchSkillAdapter.validate_coverage("targeted", [])

    def test_bonsai_preflight_missing_gguf_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            adapter = WatchSkillAdapter(executable="watch-skill")
            env = {
                "AVO_UNDERSTAND_MMPROJ": str(root / "mmproj.gguf"),
                "WATCHSKILL_CUSTOM_BASE_URL": "http://127.0.0.1:8080/v1",
            }
            with mock.patch(_RESOLVE, return_value="bonsai-27b-gguf"):
                with mock.patch.dict(os.environ, env, clear=False):
                    os.environ.pop("AVO_UNDERSTAND_GGUF", None)
                    with mock.patch.object(adapter, "run") as run:
                        with self.assertRaises(ToolError) as raised:
                            adapter.review(
                                candidate, scope="full", artifact_dir=root / "review"
                            )
            self.assertEqual(raised.exception.code, "WATCH_UNAVAILABLE")
            self.assertTrue(raised.exception.retryable)
            self.assertIn("Bonsai GGUF", raised.exception.message)
            self.assertIn("prism-ml/Bonsai-27B-gguf", raised.exception.message)
            run.assert_not_called()

    def test_bonsai_preflight_missing_mmproj_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            gguf = root / "model.gguf"
            gguf.write_bytes(b"gguf")
            adapter = WatchSkillAdapter(executable="watch-skill")
            env = {
                "AVO_UNDERSTAND_GGUF": str(gguf),
                "WATCHSKILL_CUSTOM_BASE_URL": "http://127.0.0.1:8080/v1",
            }
            with mock.patch(_RESOLVE, return_value="bonsai-27b-gguf"):
                with mock.patch.dict(os.environ, env, clear=False):
                    os.environ.pop("AVO_UNDERSTAND_MMPROJ", None)
                    with mock.patch.object(adapter, "run") as run:
                        with self.assertRaises(ToolError) as raised:
                            adapter.review(
                                candidate, scope="full", artifact_dir=root / "review"
                            )
            self.assertEqual(raised.exception.code, "WATCH_UNAVAILABLE")
            self.assertIn("mmproj", raised.exception.message.lower())
            run.assert_not_called()

    def test_bonsai_preflight_missing_custom_vision_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            gguf = root / "model.gguf"
            mmproj = root / "mmproj.gguf"
            gguf.write_bytes(b"gguf")
            mmproj.write_bytes(b"mmproj")
            adapter = WatchSkillAdapter(executable="watch-skill")
            env = {
                "AVO_UNDERSTAND_GGUF": str(gguf),
                "AVO_UNDERSTAND_MMPROJ": str(mmproj),
            }
            with mock.patch(_RESOLVE, return_value="bonsai-27b-gguf"):
                with mock.patch.dict(os.environ, env, clear=False):
                    for key in (
                        "WATCHSKILL_CUSTOM_BASE_URL",
                        "WATCHSKILL_VISION_CHEAP_PROVIDER",
                        "WATCHSKILL_VISION_STRONG_PROVIDER",
                    ):
                        os.environ.pop(key, None)
                    with mock.patch.object(adapter, "run") as run:
                        with self.assertRaises(ToolError) as raised:
                            adapter.review(
                                candidate, scope="full", artifact_dir=root / "review"
                            )
            self.assertEqual(raised.exception.code, "WATCH_UNAVAILABLE")
            message = raised.exception.message.lower()
            self.assertTrue("custom" in message or "llama.cpp" in message)
            run.assert_not_called()

    def test_bonsai_preflight_ready_keeps_watch_ask_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "proof.mp4"
            candidate.write_bytes(b"proof")
            gguf = root / "model.gguf"
            mmproj = root / "mmproj.gguf"
            gguf.write_bytes(b"gguf")
            mmproj.write_bytes(b"mmproj")
            adapter = WatchSkillAdapter(executable="watch-skill")
            env = {
                "AVO_UNDERSTAND_GGUF": str(gguf),
                "AVO_UNDERSTAND_MMPROJ": str(mmproj),
                "WATCHSKILL_CUSTOM_BASE_URL": "http://127.0.0.1:8080/v1",
            }
            with mock.patch(_RESOLVE, return_value="bonsai-27b-gguf"):
                with mock.patch.dict(os.environ, env, clear=False):
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
                                    '{"status":"pass","confidence":0.91,'
                                    '"findings":[]}\n(confidence: 0.91)'
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
            self.assertNotIn("--gguf", watch_argv)
            self.assertNotIn("--gguf", ask_argv)
            self.assertIn("--index", watch_argv)
            self.assertEqual(ask_argv[:2], ["ask", "vid-1"])
            self.assertEqual(result["status"], "pass")
