"""Explicit precision promises must survive the selected final encoder."""

from fractions import Fraction

import pytest

from avo.adapters.media.proof_executor import _output_settings


def execution(*, encoder="libx264", pixel_format="yuv420p", conformance=False):
    return {
        "output": {
            "width": 160,
            "height": 90,
            "frameRate": {"num": 24, "den": 1},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "videoCodec": encoder,
            "audioCodec": "pcm_s32le" if conformance else "aac",
            "conformance": conformance,
            "pixelFormat": pixel_format,
        },
        "audioGraph": {"sampleRate": 48000, "singleFinalEncode": True},
    }


@pytest.mark.parametrize("encoder", ["libx264", "h264_nvenc"])
@pytest.mark.parametrize("pixel_format", ["gbrp16le", "yuv420p10le", "yuv444p10le"])
def test_unqualified_precision_delivery_is_rejected_before_render(
    encoder, pixel_format
):
    selected = execution(encoder=encoder, pixel_format=pixel_format)
    with pytest.raises(RuntimeError, match="pixel format.*not qualified"):
        _output_settings(selected)


def test_explicit_supported_and_legacy_output_choices_remain_available():
    delivery = execution()
    legacy = execution()
    del legacy["output"]["pixelFormat"]
    lossless = execution(encoder="ffv1", pixel_format="gbrp16le", conformance=True)
    for selected in (delivery, legacy, lossless):
        specification, fps, rate = _output_settings(selected)
        assert specification is selected["output"]
        assert fps == Fraction(24)
        assert rate == 48000
