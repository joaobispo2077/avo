"""Delivery conversion is measured separately from lossless camera sampling."""

import subprocess
from fractions import Fraction

import numpy as np
import pytest
from tests.integration.test_camera_proof_runtime import (
    native_execution,
    pixels,
    placed_execution,
    probe,
    render,
)

from avo.adapters.media import proof_executor
from avo.adapters.media.proof_executor import execute_ffmpeg_proof

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("factory", [native_execution, placed_execution])
@pytest.mark.parametrize("fps", [Fraction(24), Fraction(30000, 1001)])
@pytest.mark.parametrize("window", [None, (7, 18)])
def test_delivery_converts_camera_picture_to_bt709_only_after_sampling(
    tmp_path, monkeypatch, factory, fps, window
):
    execution, source, _, camera = factory(tmp_path, monkeypatch, bit_depth=8, fps=fps)
    first, last = window or (0, 24)
    if window:
        execution["window"] = {"startFrame": first, "endFrameExclusive": last}
    reference = tmp_path / "camera-rgb.mkv"
    render(source, reference, camera, first=first, last=last)
    lossless = tmp_path / "native-rgb.mkv"
    execute_ffmpeg_proof(execution, lossless)
    np.testing.assert_array_equal(pixels(lossless, 160, 90), pixels(reference, 160, 90))
    expected = tmp_path / "delivery-reference.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-filter_threads",
            "1",
            "-i",
            str(reference),
            "-vf",
            (
                "scale=in_range=full:out_range=limited:out_color_matrix=bt709,"
                "format=yuv420p,setparams=range=tv:color_primaries=bt709:"
                "color_trc=bt709:colorspace=bt709"
            ),
            "-an",
            "-c:v",
            "ffv1",
            "-frames:v",
            str(last - first),
            "-r",
            str(fps),
            str(expected),
        ],
        capture_output=True,
        check=True,
    )
    execution["output"].update(
        videoCodec="libx264",
        audioCodec="aac",
        conformance=False,
        pixelFormat="yuv420p",
    )

    # Tap the actual delivery filter output with a lossless encoder. Independent
    # H.264 runs can choose different prediction/quantization; their decoded RGB
    # equality does not isolate the camera or color conversion.
    def capture_conversion(spec, rate, count):
        return [
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s32le",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(rate),
            "-frames:v",
            str(count),
            "-f",
            "matroska",
        ]

    converted = tmp_path / "delivery-filter-output.mkv"
    with monkeypatch.context() as patch:
        patch.setattr(proof_executor, "_encode_arguments", capture_conversion)
        execute_ffmpeg_proof(execution, converted)
    np.testing.assert_array_equal(pixels(converted, 160, 90), pixels(expected, 160, 90))
    actual = tmp_path / "delivery.mp4"
    execute_ffmpeg_proof(execution, actual)
    metadata = probe(actual)
    assert metadata["pix_fmt"] == "yuv420p"
    assert metadata["color_space"] == "bt709"
    assert metadata["color_range"] == "tv"
    assert metadata["sample_aspect_ratio"] == "1:1"
    assert pixels(actual, 160, 90).shape == (last - first, 90, 160, 3)
