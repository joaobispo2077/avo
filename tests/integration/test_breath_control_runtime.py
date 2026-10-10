"""Real FFmpeg: unchanged sidechains, samples, and duration."""

import shutil
import subprocess

import numpy as np
import pytest

from avo.adapters.media.audio_tracks import compile_audio_layers
from avo.breath_control import apply_control
from avo.breath_mix import materialize_breath_mix
from avo.timeline.contracts import file_fingerprint

pytestmark = pytest.mark.integration


def _render(layers, files):
    compiled = compile_audio_layers(layers, first_input_index=0)
    cmd = ["ffmpeg", "-v", "error", "-filter_complex_threads", "1"]
    for path in files:
        cmd += ["-f", "f32le", "-ar", "48000", "-ac", "2", "-i", str(path)]
    cmd += [
        "-filter_complex",
        ";".join(compiled["filters"]),
        "-map",
        "[outa]",
        "-f",
        "f32le",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    return np.frombuffer(result.stdout, dtype=np.float32).reshape(-1, 2)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg unavailable")
def test_real_mix_delta_is_only_breath_delta_even_with_music_sidechain(tmp_path):
    rate = 48000
    time = np.arange(rate) / rate
    dialogue = np.repeat(
        (0.15 * np.sin(2 * np.pi * 230 * time))[:, None], 2, axis=1
    ).astype(np.float32)
    music = np.repeat(
        (0.05 * np.sin(2 * np.pi * 90 * time))[:, None], 2, axis=1
    ).astype(np.float32)
    files = [tmp_path / "dialogue.pcm", tmp_path / "music.pcm"]
    for pcm, path in zip((dialogue, music), files):
        pcm.tofile(path)
    layers = [
        {
            "layerId": "dialogue",
            "role": "dialogue",
            "order": 0,
            "source": {"locator": str(files[0]), "sha256": "a" * 64},
            "regions": [{"startTicks": 0, "endTicks": 1000}],
        },
        {
            "layerId": "music",
            "role": "music",
            "order": 1,
            "source": {"locator": str(files[1])},
            "ducking": {"amountDb": 8},
            "regions": [{"startTicks": 0, "endTicks": 750}],
        },
    ]
    control = {
        "enabled": True,
        "sampleRate": rate,
        "sourceSha256": "a" * 64,
        "transcriptSha256": "b" * 64,
        "protectedRanges": [],
        "events": [
            {
                "eventId": "breath-001",
                "startSample": 9600,
                "endSampleExclusive": 28800,
                "status": "confirmed",
                "breathRmsDb": -20,
                "speechRmsDb": -10,
            }
        ],
    }
    layers[0]["breathControl"] = control
    for layer, path in zip(layers, files):
        wav = path.with_suffix(".wav")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "f32le",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-i",
                str(path),
                "-c:a",
                "pcm_f32le",
                str(wav),
            ],
            check=True,
        )
        layer["source"] = file_fingerprint(wav)
    control["sourceSha256"] = layers[0]["source"]["sha256"]
    result = materialize_breath_mix(layers, tmp_path / "freeze")
    before = np.fromfile(
        tmp_path / "freeze" / "baseline.f32le", dtype=np.float32
    ).reshape(-1, 2)
    frozen_dialogue = np.fromfile(
        tmp_path / "freeze" / "dialogue.f32le", dtype=np.float32
    ).reshape(-1, 2)
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(result["path"]), "-f", "f32le", "pipe:1"],
        capture_output=True,
        check=True,
    )
    after = np.frombuffer(decoded.stdout, dtype=np.float32).reshape(-1, 2)
    _, delta = apply_control(frozen_dialogue, control, rate)
    assert len(after) == len(before) == rate
    np.testing.assert_allclose(before - after, delta, atol=2e-7)
    np.testing.assert_array_equal(after[:9600], before[:9600])
    np.testing.assert_array_equal(after[28800:], before[28800:])


def test_wrong_role_and_stale_source_are_rejected():
    control = {"enabled": True, "sourceSha256": "a" * 64}
    for role, digest in (("music", "a" * 64), ("dialogue", "b" * 64)):
        with pytest.raises(ValueError):
            compile_audio_layers(
                [
                    {
                        "layerId": "test",
                        "role": role,
                        "source": {"sha256": digest},
                        "breathControl": control,
                    }
                ]
            )


def test_live_ducking_fails_closed_instead_of_altering_music_tail():
    control = {
        "enabled": True,
        "sourceSha256": "a" * 64,
        "events": [
            {
                "eventId": "breath-001",
                "startSample": 4800,
                "endSampleExclusive": 24000,
                "status": "confirmed",
                "breathRmsDb": -20,
                "speechRmsDb": -10,
            }
        ],
    }
    layers = [
        {
            "layerId": "dialogue",
            "role": "dialogue",
            "source": {"sha256": "a" * 64},
            "breathControl": control,
        },
        {"layerId": "music", "role": "music", "ducking": {"amountDb": 8}},
    ]
    with pytest.raises(ValueError, match="frozen PCM"):
        compile_audio_layers(layers)
