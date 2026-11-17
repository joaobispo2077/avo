"""NVENC quality settings must preserve CPU and lossless encode contracts."""

from fractions import Fraction
from pathlib import Path

from avo.adapters.media import proof_executor

NVENC_QUALITY = [
    "-preset",
    "p5",
    "-tune",
    "hq",
    "-rc",
    "vbr",
    "-cq",
    "19",
    "-b:v",
    "12M",
    "-maxrate",
    "18M",
    "-bufsize",
    "36M",
    "-profile:v",
    "high",
]
NORMAL_OUTPUT = [
    "-color_range",
    "tv",
    "-colorspace",
    "bt709",
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
    "-b:a",
    "192k",
    "-movie_timescale",
    "48000",
    "-movflags",
    "+faststart",
]


def settings(codec, *, conformance=False):
    return {
        "videoCodec": codec,
        "audioCodec": "pcm_s32le" if conformance else "aac",
        "audioSampleRate": 48000,
        "conformance": conformance,
    }


def test_nvenc_uses_qualified_quality_target_and_bitrate_cap():
    arguments = proof_executor._encode_arguments(
        settings("h264_nvenc"), Fraction(60), 240
    )
    assert arguments == [
        "-c:v",
        "h264_nvenc",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-r",
        "60/1",
        "-frames:v",
        "240",
        *NVENC_QUALITY,
        *NORMAL_OUTPUT,
    ]


def test_cpu_encode_arguments_remain_exactly_unchanged():
    assert proof_executor._encode_arguments(settings("libx264"), Fraction(60), 240) == [
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-r",
        "60/1",
        "-frames:v",
        "240",
        *NORMAL_OUTPUT,
    ]


def test_conformance_encode_remains_lossless_without_hardware_quality_flags():
    assert proof_executor._encode_arguments(
        settings("ffv1", conformance=True), Fraction(60), 240
    ) == [
        "-c:v",
        "ffv1",
        "-c:a",
        "pcm_s32le",
        "-ar",
        "48000",
        "-r",
        "60/1",
        "-frames:v",
        "240",
        "-pix_fmt",
        "bgra",
        "-f",
        "matroska",
    ]


def test_final_encoder_keeps_nvenc_quality_and_finite_audio_contract():
    arguments, metadata = proof_executor._final_arguments(
        ["-f", "rawvideo", "-i", "pipe:0"],
        Path("candidate.mp4"),
        [],
        settings("h264_nvenc"),
        Fraction(60),
        0,
        240,
        Path("mix.wav"),
    )
    assert metadata == []
    assert "-frames:v" not in arguments
    assert (
        "[v]trim=end_frame=240[bounded-picture]"
        in arguments[arguments.index("-filter_complex") + 1]
    )
    assert arguments[-(len(NVENC_QUALITY) + len(NORMAL_OUTPUT) + 1) : -1] == [
        *NVENC_QUALITY,
        *NORMAL_OUTPUT,
    ]
