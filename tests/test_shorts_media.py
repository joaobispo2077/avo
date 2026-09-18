from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from avo import shorts_media


class ShortsMediaTests(unittest.TestCase):
    def test_ordered_segments_concat_picture_and_dialogue_without_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            commands = []

            def runner(argv):
                commands.append(list(argv))
                Path(argv[-1]).parent.mkdir(parents=True, exist_ok=True)
                Path(argv[-1]).write_bytes(str(len(commands)).encode())
                return subprocess.CompletedProcess(argv, 0, "", "")

            result = shorts_media.prepare_ordered_base_assets(
                source,
                root / "prepared",
                source_segments=[
                    {"segmentId": "01-s001", "order": 1, "startSec": 10, "endSec": 12},
                    {"segmentId": "01-s002", "order": 2, "startSec": 1, "endSec": 4},
                ],
                speed=1,
                runner=runner,
            )
            self.assertEqual(result["baseVideo"].duration_sec, 5)
            self.assertEqual(result["dialogueAudio"].duration_sec, 5)
            self.assertEqual(len(result["joinWindows"]), 1)
            self.assertAlmostEqual(result["joinWindows"][0]["start"], 1.985)
            self.assertIn("concat=n=2:v=1:a=0", " ".join(commands[-2]))
            self.assertIn("d=0.030", " ".join(commands[-1]))

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
        with tempfile.TemporaryDirectory() as tmp:
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
        with tempfile.TemporaryDirectory() as tmp:
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

    def test_ducked_mix_uses_sidechain_and_does_not_stack_volume(self) -> None:
        command = shorts_media.ducked_mix_command(
            Path("voice.m4a"),
            Path("bed.m4a"),
            Path("mix.m4a"),
        )
        filters = command[command.index("-filter_complex") + 1]
        self.assertIn("sidechaincompress=", filters)
        self.assertIn("attack=20", filters)
        self.assertIn("release=250", filters)
        self.assertIn("normalize=0", filters)
        self.assertNotIn("volume=", filters)
        self.assertEqual(command[command.index("-ar") + 1], "48000")

    def test_dialogue_gain_filter_only_when_outside_band(self) -> None:
        self.assertIsNone(shorts_media.dialogue_gain_filter(-16.0, -2.0))
        self.assertIn("volume=", shorts_media.dialogue_gain_filter(-28.0, -12.0) or "")
        self.assertIn("volume=", shorts_media.dialogue_gain_filter(-16.0, 1.0) or "")
        self.assertIn("volume=", shorts_media.dialogue_gain_filter(-35.6, -16.1) or "")
        self.assertIn(
            "volume=",
            shorts_media.dialogue_gain_filter(-13.7, -1.0, tp_ceiling=-5.0) or "",
        )

    def test_composition_assets_omit_insertion_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dialogue = root / "dialogue.m4a"
            bed = root / "bed.m4a"
            dialogue.write_bytes(b"a")
            bed.write_bytes(b"b")
            prepared = {
                "dialogueAudio": shorts_media.PreparedAsset(
                    dialogue, "a" * 64, 2.0, False
                ),
                "insertionAudio": shorts_media.PreparedAsset(bed, "b" * 64, 2.0, False),
                "joinWindows": [],
            }
            assets = shorts_media.composition_assets(prepared)
            self.assertIn("dialogueAudio", assets)
            self.assertNotIn("insertionAudio", assets)

    def test_sfx_command_resamples_to_48k_stereo_aac(self) -> None:
        command = shorts_media.sfx_audio_command(Path("tick.wav"), Path("sfx-chip.m4a"))
        self.assertEqual(command[command.index("-ar") + 1], "48000")
        self.assertEqual(command[command.index("-ac") + 1], "2")
        self.assertEqual(command[command.index("-c:a") + 1], "aac")

    def test_prepare_sfx_assets_copies_used_kinds_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "tick.wav"
            source.write_bytes(b"tick")
            commands = []

            def runner(argv):
                commands.append(list(argv))
                if argv[0] == "ffprobe":
                    return subprocess.CompletedProcess(
                        argv,
                        0,
                        json.dumps({"format": {"duration": "0.44"}}),
                        "",
                    )
                Path(argv[-1]).parent.mkdir(parents=True, exist_ok=True)
                Path(argv[-1]).write_bytes(b"sfx")
                return subprocess.CompletedProcess(argv, 0, "", "")

            assets = shorts_media.prepare_sfx_assets(
                [{"id": "s01-chip-sfx", "kind": "chip", "startSec": 1.0}],
                {"chip": str(source), "stamp": str(root / "missing.wav")},
                root / "prepared-sfx",
                request_path=root / "shorts.request.json",
                runner=runner,
            )
            self.assertIn("sfxChip", assets)
            self.assertNotIn("sfxStamp", assets)
            self.assertEqual(assets["sfxChip"].duration_sec, 0.44)

    def test_composition_assets_include_prepared_sfx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dialogue = root / "dialogue.m4a"
            tick = root / "sfx-chip.m4a"
            dialogue.write_bytes(b"a")
            tick.write_bytes(b"s")
            prepared = {
                "dialogueAudio": shorts_media.PreparedAsset(
                    dialogue, "a" * 64, 2.0, False
                ),
                "sfxChip": shorts_media.PreparedAsset(tick, "b" * 64, 0.44, False),
                "joinWindows": [],
            }
            assets = shorts_media.composition_assets(prepared)
            self.assertIn("sfxChip", assets)
            self.assertNotIn("joinWindows", assets)


if __name__ == "__main__":
    unittest.main()
