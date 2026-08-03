from __future__ import annotations

import unittest

from avo import loudness_profiles


class LoudnessProfilesTests(unittest.TestCase):
    def test_platform_fit_shorts_preset(self) -> None:
        project = {"deliverable": {"profile": "shorts"}, "audio": {"loudness_intent": "platform_fit"}}
        profile = loudness_profiles.resolve_loudness_profile(project=project)
        self.assertEqual(profile.preset_id, "youtube_shorts")
        self.assertEqual(profile.integrated_lufs, -14.0)
        self.assertEqual(profile.true_peak_dbtp, -1.0)
        self.assertEqual(profile.lra_lu, 11.0)

    def test_channel_standard_uses_provider(self) -> None:
        provider = {
            "loudness": {
                "default_intent": "channel_standard",
                "channel_standard": {
                    "integrated_lufs": -16.0,
                    "true_peak_dbtp": -1.0,
                    "lra_lu": 9.0,
                },
            }
        }
        profile = loudness_profiles.resolve_loudness_profile(provider=provider)
        self.assertEqual(profile.intent, "channel_standard")
        self.assertEqual(profile.integrated_lufs, -16.0)
        self.assertEqual(profile.source, "provider.channel_standard")

    def test_preserve_dynamics_adjusts_lra(self) -> None:
        project = {
            "audio": {
                "loudness_intent": "platform_fit",
                "loudness_preset": "youtube_long_form_speech",
                "loudness_range_preference": "preserve_dynamics",
            }
        }
        profile = loudness_profiles.resolve_loudness_profile(project=project)
        self.assertEqual(profile.lra_lu, 11.0)

    def test_tight_caps_lra(self) -> None:
        project = {
            "audio": {
                "loudness_intent": "platform_fit",
                "loudness_preset": "youtube_shorts",
                "loudness_range_preference": "tight",
            }
        }
        profile = loudness_profiles.resolve_loudness_profile(project=project)
        self.assertEqual(profile.lra_lu, 7.0)

    def test_creative_requires_approval_when_hot(self) -> None:
        project = {
            "audio": {
                "loudness_intent": "creative",
                "loudness_custom": {
                    "integrated_lufs": -10.0,
                    "true_peak_dbtp": -1.0,
                },
            }
        }
        with self.assertRaises(ValueError):
            loudness_profiles.resolve_loudness_profile(project=project)

    def test_creative_with_approval(self) -> None:
        project = {
            "audio": {
                "loudness_intent": "creative",
                "loudness_custom": {
                    "integrated_lufs": -12.0,
                    "true_peak_dbtp": -1.0,
                    "approved_by_user": True,
                },
            }
        }
        profile = loudness_profiles.resolve_loudness_profile(project=project)
        self.assertEqual(profile.integrated_lufs, -12.0)

    def test_cli_preset_override(self) -> None:
        profile = loudness_profiles.resolve_loudness_profile(preset_override="tiktok")
        self.assertEqual(profile.preset_id, "tiktok")
        self.assertEqual(profile.source, "cli_override")

    def test_evaluate_qc_pass(self) -> None:
        profile = loudness_profiles.resolve_loudness_profile(
            project={"audio": {"loudness_preset": "youtube_shorts", "loudness_intent": "platform_fit"}}
        )
        measurement = {"input_i": "-14.2", "input_tp": "-1.5", "input_lra": "10.0"}
        result = loudness_profiles.evaluate_qc(measurement, profile)
        self.assertEqual(result["status"], "PASS")

    def test_evaluate_qc_fail_integrated(self) -> None:
        profile = loudness_profiles.resolve_loudness_profile(
            project={"audio": {"loudness_preset": "youtube_shorts", "loudness_intent": "platform_fit"}}
        )
        measurement = {"input_i": "-11.0", "input_tp": "-1.5", "input_lra": "10.0"}
        result = loudness_profiles.evaluate_qc(measurement, profile)
        self.assertEqual(result["status"], "FAIL")

    def test_nr_warning(self) -> None:
        edl = {
            "audio": {
                "restoration_segments": [{"strength_pct": 70, "approved_by_user": True}],
            }
        }
        profile = loudness_profiles.resolve_loudness_profile(
            edl=edl,
            project={"audio": {"loudness_preset": "youtube_shorts", "loudness_intent": "platform_fit"}},
        )
        warning = loudness_profiles.nr_loudness_warning(edl, profile)
        self.assertIsNotNone(warning)

    def test_resolver_is_deterministic(self) -> None:
        project = {"deliverable": {"profile": "tiktok"}, "audio": {"loudness_intent": "platform_fit"}}
        first = loudness_profiles.resolve_loudness_profile(project=project)
        second = loudness_profiles.resolve_loudness_profile(project=project)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_legacy_warning_when_undeclared(self) -> None:
        profile = loudness_profiles.resolve_loudness_profile()
        self.assertTrue(profile.legacy_warning)

    def test_loudnorm_disabled_flag(self) -> None:
        project = {"audio": {"loudnorm_enabled": False}}
        profile = loudness_profiles.resolve_loudness_profile(project=project)
        self.assertFalse(profile.loudnorm_enabled)


if __name__ == "__main__":
    unittest.main()
