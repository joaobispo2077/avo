"""Ducking must not discard samples when either input reaches EOF."""

import shutil
import subprocess

import numpy as np
import pytest

from avo.adapters.media.audio_tracks import compile_audio_layers

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg unavailable")
@pytest.mark.parametrize(
    "dialogue_ms,music_ms,start_ms", [(100, 350, 0), (350, 100, 125)]
)
def test_ducking_preserves_declared_music_tail(
    tmp_path, dialogue_ms, music_ms, start_ms
):
    layers = []
    command = ["ffmpeg", "-v", "error"]
    for order, (role, duration, value) in enumerate(
        [("dialogue", dialogue_ms, 0.001), ("music", music_ms, 0.01)]
    ):
        path = tmp_path / f"{role}.pcm"
        np.full((duration * 48, 2), value, dtype=np.float32).tofile(path)
        command += ["-f", "f32le", "-ar", "48000", "-ac", "2", "-i", str(path)]
        start = start_ms if role == "music" else 0
        layers.append(
            {
                "layerId": role,
                "role": role,
                "order": order,
                "source": {"locator": str(path)},
                "regions": [{"startTicks": start, "endTicks": start + duration}],
                **({"ducking": {"amountDb": 8}} if role == "music" else {}),
            }
        )
    graph = compile_audio_layers(layers, first_input_index=0)
    command += [
        "-filter_complex",
        ";".join(graph["filters"]),
        "-map",
        "[outa]",
        "-f",
        "f32le",
        "pipe:1",
    ]
    expected = np.zeros((max(dialogue_ms, start_ms + music_ms) * 48, 2), np.float32)
    expected[: dialogue_ms * 48] += np.float32(0.001)
    expected[start_ms * 48 : (start_ms + music_ms) * 48] += np.float32(0.01)
    for _ in range(3):
        result = subprocess.run(command, capture_output=True, check=True, timeout=15)
        actual = np.frombuffer(result.stdout, np.float32).reshape(-1, 2)
        np.testing.assert_array_equal(actual, expected)
