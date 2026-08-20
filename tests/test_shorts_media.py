from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from avo import shorts_media


class ShortsMediaTests(unittest.TestCase):
    def test_video_command_trims_retimes_normalizes_cfr_and_has_no_audio(self) -> None:
        command = shorts_media.base_video_command(
            Path("H:/footage/base clip.mp4"),
            Path("proof/base.mp4"),
            start_sec=10,
            end_sec=22,
            speed=1.2,
            fps=30,
            width=1080,
            height=1920,
        )
        self.assertIn("setpts=(PTS-STARTPTS)/1.2", command[command.index("-vf") + 1])
        self.assertIn("fps=30", command[command.index("-vf") + 1])
        self.assertIn("-an", command)
        self.assertEqual(command[command.index("-t") + 1], "10.000000")
        self.assertIn(str(Path("H:/footage/base clip.mp4")), command)

    def test_contain_crop_mode_pads_instead_of_cropping(self) -> None:
        command = shorts_media.base_video_command(
            Path("base.mp4"),
            Path("proof/base.mp4"),
            start_sec=0,
            end_sec=10,
            speed=1.0,
            fps=30,
            width=1080,
            height=1920,
            crop_mode="contain",
        )
        self.assertIn(
            "force_original_aspect_ratio=decrease", command[command.index("-vf") + 1]
        )
        self.assertIn("pad=1080:1920", command[command.index("-vf") + 1])

    def test_audio_command_preserves_pitch_and_uses_same_exact_duration(self) -> None:
        command = shorts_media.dialogue_audio_command(
            Path("base.mp4"),
            Path("dialogue.m4a"),
            start_sec=10,
            end_sec=22,
            speed=1.2,
        )
        self.assertIn("atempo=1.2", command[command.index("-af") + 1])
        self.assertEqual(command[command.index("-t") + 1], "10.000000")
        self.assertEqual(command[command.index("-ar") + 1], "48000")

    def test_extreme_tempo_is_decomposed_into_supported_filters(self) -> None:
        self.assertEqual(shorts_media.atempo_chain(4), "atempo=2,atempo=2")
        self.assertEqual(shorts_media.atempo_chain(0.25), "atempo=0.5,atempo=0.5")

    def test_injected_runner_creates_hashed_separate_assets(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            root = Path(tmp)
            source = root / "base.mp4"
            source.write_bytes(b"source")
            commands = []

            def runner(argv):
                commands.append(list(argv))
                Path(argv[-1]).write_bytes(str(len(commands)).encode())
                return subprocess.CompletedProcess(argv, 0, "", "")

            assets = shorts_media.prepare_base_assets(
                source,
                root / "assets",
                start_sec=0,
                end_sec=12,
                speed=1.2,
                runner=runner,
            )
            self.assertEqual(len(commands), 2)
            self.assertTrue(assets["baseVideo"].muted)
            self.assertEqual(len(assets["dialogueAudio"].sha256), 64)

    def test_finite_repeat_never_uses_excluded_tail_and_covers_exact_duration(
        self,
    ) -> None:
        approved = [{"startSec": 5, "endSec": 10}]
        source_map = shorts_media.finite_repeat_map(approved, 12)
        shorts_media.validate_source_map(
            source_map, approved, [{"startSec": 10, "endSec": 20}], 12
        )
        self.assertEqual(source_map[-1]["outputEndSec"], 12)
        self.assertEqual(source_map[-1]["sourceEndSec"], 7)

    def test_insertion_commands_map_only_declared_streams(self) -> None:
        source_map = shorts_media.finite_repeat_map([{"startSec": 5, "endSec": 10}], 7)
        video, audio = shorts_media.insertion_commands(
            Path("gameplay.mkv"),
            Path("out"),
            source_map,
            video_stream="0:v:0",
            audio_stream="0:a:3",
            support_volume=0.2,
        )
        self.assertIn("[0:v:0]trim", video[video.index("-filter_complex") + 1])
        self.assertIn("[0:a:3]atrim", audio[audio.index("-filter_complex") + 1])
        self.assertNotIn("0:a:0", " ".join(audio))

    def test_provenance_rejects_gap_and_excluded_window(self) -> None:
        with self.assertRaises(shorts_media.MediaPreparationError):
            shorts_media.validate_source_map(
                [
                    {
                        "outputStartSec": 1,
                        "outputEndSec": 2,
                        "sourceStartSec": 5,
                        "sourceEndSec": 6,
                    }
                ],
                [{"startSec": 5, "endSec": 10}],
                [],
                2,
            )

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required"
    )
    def test_real_finite_repeat_excludes_forbidden_tail_and_selects_audio_track(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            root = Path(tmp)
            source = root / "source.mkv"
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=160x90:r=30:d=3",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=160x90:r=30:d=1",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo:d=4",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:sample_rate=48000:duration=4",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map",
                "[v]",
                "-map",
                "2:a",
                "-map",
                "3:a",
                "-c:v",
                "ffv1",
                "-c:a",
                "pcm_s16le",
                str(source),
            ]
            subprocess.run(command, check=True)
            assets, source_map = shorts_media.prepare_insertion_assets(
                source,
                root / "prepared",
                approved_windows=[{"startSec": 0, "endSec": 3}],
                excluded_windows=[{"startSec": 3, "endSec": 4}],
                target_duration=5,
                video_stream="0:v:0",
                audio_stream="0:a:1",
                support_volume=0.2,
            )
            self.assertEqual(source_map[-1]["sourceEndSec"], 2)
            probe = shorts_media.probe_media(assets["insertionVideo"].path)
            self.assertAlmostEqual(float(probe["format"]["duration"]), 5, delta=0.08)
            raw = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    "4.5",
                    "-i",
                    str(assets["insertionVideo"].path),
                    "-vf",
                    "scale=1:1,format=rgb24",
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-",
                ],
                check=True,
                capture_output=True,
            ).stdout
            red, green, _blue = raw[:3]
            self.assertGreater(green, red)
            audio_stats = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-i",
                    str(assets["insertionAudio"].path),
                    "-af",
                    "volumedetect",
                    "-f",
                    "null",
                    "-",
                ],
                text=True,
                capture_output=True,
            ).stderr
            self.assertNotIn("mean_volume: -inf", audio_stats)


if __name__ == "__main__":
    unittest.main()
