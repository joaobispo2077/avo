"""Frame-based generated ranges survive Matroska millisecond timestamp rounding."""

import json
import subprocess
from fractions import Fraction

import numpy as np

from avo.adapters.media.proof_executor import _picture_source, _render_piece


def test_generated_range_starts_on_declared_frame_not_next_millisecond(tmp_path):
    frames = np.zeros((12, 24, 32, 4), dtype=np.uint8)
    frames[:, :, :, 3] = 255
    for index in range(12):
        frames[index, :, :, :3] = index * 17
    source = tmp_path / "base.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-s",
            "32x24",
            "-r",
            "60",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "ffv1",
            str(source),
        ],
        input=frames.tobytes(),
        check=True,
        capture_output=True,
    )
    video = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(source)]
        )
    )["streams"][0]
    operation = {
        "operationId": "slice",
        "kind": "generated-clip",
        "outputRange": {"startFrame": 0, "endFrameExclusive": 4},
        "parameters": {"sourceRange": {"startFrame": 2, "endFrameExclusive": 6}},
    }
    fps = Fraction(60)
    picture, start, duration, tail = _picture_source(
        operation, {"slice": {"path": source, "video": video}}, {}, {}, fps
    )
    node = {
        "kind": "silence",
        "outputRange": {"startSample": 0, "endSampleExclusive": 3200},
    }
    segment = (0, 4, picture, start, duration, node, None, (0, 0), None, tail, None)
    output = tmp_path / "slice.mkv"
    _render_piece(
        segment,
        0,
        4,
        {"width": 32, "height": 24, "conformance": True},
        fps,
        48000,
        output,
    )
    decoded = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(output),
            "-map",
            "0:v:0",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-",
        ]
    )
    actual = np.frombuffer(decoded, np.uint8).reshape(-1, 24, 32, 4)
    np.testing.assert_array_equal(actual, frames[2:6])
