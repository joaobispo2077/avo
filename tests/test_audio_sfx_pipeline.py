from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from avo import generate_sfx
from avo import render


class AudioSfxPipelineTests(unittest.TestCase):
    def test_sfx_are_deterministic_stereo_48k(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in generate_sfx.EFFECT_NAMES:
                first = root / f"{name}-1.wav"
                second = root / f"{name}-2.wav"
                generate_sfx.generate_effect(name, first)
                generate_sfx.generate_effect(name, second)
                self.assertEqual(
                    hashlib.sha256(first.read_bytes()).hexdigest(),
                    hashlib.sha256(second.read_bytes()).hexdigest(),
                )
                with wave.open(str(first), "rb") as wav:
                    self.assertEqual(wav.getframerate(), 48000)
                    self.assertEqual(wav.getnchannels(), 2)
                    self.assertEqual(wav.getsampwidth(), 2)

    def test_audio_filter_uses_negative_gain_delay_and_stereo_mix(self) -> None:
        effects = [
            {
                "start_in_output": 2.25,
                "duration": 0.5,
                "gain_db": -12,
                "motion_brief_id": "transfer-direction",
            }
        ]
        parts, output = render.build_audio_filter_parts(effects, first_input_index=4)
        graph = ";".join(parts)
        self.assertEqual(output, "[outa]")
        self.assertIn("channel_layouts=stereo", graph)
        self.assertIn("volume=-12.000dB", graph)
        self.assertIn("adelay=2250|2250", graph)
        self.assertIn("amix=inputs=2", graph)

    def test_comparison_sfx_names_are_available_but_optional(self) -> None:
        for name in ["soft_whoosh", "tick", "price_pop", "transition_hit", "verification_chime"]:
            self.assertIn(name, generate_sfx.EFFECT_NAMES)
        parts, output = render.build_audio_filter_parts([], first_input_index=1)
        self.assertEqual(parts, [])
        self.assertEqual(output, "0:a:0")

    def test_audio_policy_selects_clean_stereo_track_and_youtube_output(self) -> None:
        edl = {
            "audio": {
                "main_source_stream": "a:2",
                "output_channels": 2,
                "sample_rate_hz": 48000,
                "ad_audio_policy": "select_cleanest_stereo_track",
            }
        }
        self.assertEqual(render.audio_source_stream(edl), "a:2")
        self.assertEqual(render.output_audio_channels(edl), 2)
        self.assertEqual(render.output_sample_rate(edl), 48000)

    def test_v004_cash_and_switch_ui_sfx_names_are_available(self) -> None:
        for name in [
            "cash_register_money",
            "coin_tick",
            "receipt_print",
            "card_confirm",
            "switch_ui_click",
            "switch_ui_chime",
            "soft_transition",
        ]:
            self.assertIn(name, generate_sfx.EFFECT_NAMES)

    def test_v004_audio_policy_requires_conservative_denoise_and_stereo_dialogue_qc(self) -> None:
        edl = {
            "audio": {
                "main_source_stream": "a:0",
                "output_channels": 2,
                "sample_rate_hz": 48000,
                "noise_reduction_policy": "conservative_speech_first",
                "channel_qc": "passed_left_right_dialogue_audible",
            }
        }
        self.assertEqual(edl["audio"]["noise_reduction_policy"], "conservative_speech_first")
        self.assertEqual(edl["audio"]["channel_qc"], "passed_left_right_dialogue_audible")

    def test_feature_005_main_source_gets_youtube_dialogue_eq(self) -> None:
        edl = {"audio": {"noise_reduction_policy": "conservative_speech_first"}}
        chain = render.audio_repair_filter_for(edl, "main")
        self.assertIn("highpass=f=90", chain)
        self.assertIn("equalizer=f=250", chain)
        self.assertIn("equalizer=f=3400", chain)
        self.assertIn("afftdn=nr=8", chain)
        self.assertIn("lowpass=f=16000", chain)

    def test_youtube_true_peak_limiter_matches_minus_three_dbtp(self) -> None:
        self.assertIn("limit=0.630", render.LIMITER_FILTER)


if __name__ == "__main__":
    unittest.main()

