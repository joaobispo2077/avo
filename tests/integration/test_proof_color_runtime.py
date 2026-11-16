"""Qualify portable SDR colour conversion using actual native final encodes."""

import shutil
import subprocess
from fractions import Fraction

import numpy as np
import pytest

from avo.adapters.media import proof_executor
from avo.timeline.contracts import file_fingerprint

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
        reason="Actual FFmpeg/FFprobe required",
    ),
]

FPS, COUNT, WIDTH, HEIGHT, RATE = 24, 12, 192, 96, 48000


def run(arguments, *, data=None):
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", *arguments],
        input=data,
        capture_output=True,
        timeout=60,
        check=True,
    ).stdout


def decode_picture(path):
    return np.frombuffer(
        run(
            [
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-vf",
                "scale=in_color_matrix=bt709:out_range=full,format=rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ]
        ),
        dtype=np.uint8,
    ).reshape(-1, HEIGHT, WIDTH, 3)


def decode_audio(path, pixel_format):
    return np.frombuffer(
        run(
            [
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-c:a",
                "pcm_" + pixel_format,
                "-f",
                pixel_format,
                "pipe:1",
            ]
        ),
        dtype=np.int32 if pixel_format == "s32le" else np.float32,
    ).reshape(-1, 2)


def patch_interiors(frames):
    # Leave an eight-pixel margin around every subsampled chroma boundary.
    return np.stack(
        [
            frames[:, y + 8 : y + 40, x + 8 : x + 56]
            for y in (0, 48)
            for x in (0, 64, 128)
        ],
        axis=1,
    )


def best_audio_lag(actual, expected):
    correlations = {}
    for lag in range(-32, 33):
        first, second = max(0, lag), max(0, -lag)
        count = min(len(actual) - first, len(expected) - second)
        correlations[lag] = np.corrcoef(
            actual[first : first + count], expected[second : second + count]
        )[0, 1]
    return max(correlations, key=correlations.get)


@pytest.fixture(scope="module")
def final_outputs(tmp_path_factory):
    directory = tmp_path_factory.mktemp("native-sdr-colour")
    source, mixed = directory / "picture.mkv", directory / "mix.wav"
    colours = np.array(
        [
            [[214, 42, 66], [32, 188, 80], [45, 76, 222]],
            [[218, 193, 44], [34, 188, 203], [198, 42, 189]],
        ],
        dtype=np.uint8,
    )
    frame = np.repeat(np.repeat(colours, 48, axis=0), 64, axis=1)
    picture = np.repeat(frame[None], COUNT, axis=0)
    run(
        [
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{WIDTH}x{HEIGHT}",
            "-framerate",
            str(FPS),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "bgra",
            str(source),
        ],
        data=picture.tobytes(),
    )
    time = np.arange(COUNT * RATE // FPS, dtype=np.float64) / RATE
    audio = np.column_stack(
        (0.09 * np.sin(2 * np.pi * 440 * time), 0.06 * np.sin(2 * np.pi * 770 * time))
    ).astype(np.float32)
    run(
        [
            "-f",
            "f32le",
            "-ar",
            str(RATE),
            "-ac",
            "2",
            "-i",
            "pipe:0",
            "-c:a",
            "pcm_s32le",
            str(mixed),
        ],
        data=audio.tobytes(),
    )
    original = [file_fingerprint(path) for path in (source, mixed)]
    listing = directory / "concat.txt"
    listing.write_text("file 'picture.mkv'\n", encoding="utf-8")
    outputs = {}
    for conformance in (False, True):
        path = directory / ("conformance.mkv" if conformance else "normal.mp4")
        spec = {
            "width": WIDTH,
            "height": HEIGHT,
            "videoCodec": "ffv1" if conformance else "libx264",
            "audioCodec": "pcm_s32le" if conformance else "aac",
            "audioSampleRate": RATE,
            "conformance": conformance,
        }
        media, metadata = proof_executor._render_final(
            listing, path, [], spec, Fraction(FPS), 0, COUNT, mixed_audio=mixed
        )
        assert metadata == []
        assert [file_fingerprint(item) for item in (source, mixed)] == original
        outputs[conformance] = (path, media)
    return outputs, picture, decode_audio(mixed, "s32le")


def test_normal_sdr_final_encode_declares_complete_bt709_contract(final_outputs):
    outputs, _, _ = final_outputs
    _, media = outputs[False]
    video, audio = media["streams"]
    assert video["codec_type"] == "video" and video["codec_name"] == "h264"
    assert video["pix_fmt"] == "yuv420p"
    assert (video["width"], video["height"]) == (WIDTH, HEIGHT)
    assert Fraction(video["r_frame_rate"]) == FPS
    assert int(video["nb_read_frames"]) == COUNT
    assert {
        key: video.get(key)
        for key in ("color_range", "color_space", "color_primaries", "color_transfer")
    } == {
        "color_range": "tv",
        "color_space": "bt709",
        "color_primaries": "bt709",
        "color_transfer": "bt709",
    }
    assert audio["codec_type"] == "audio" and audio["codec_name"] == "aac"
    assert int(audio["sample_rate"]) == RATE and audio["channels"] == 2
    assert abs(float(audio["duration"]) - COUNT / FPS) <= 1 / RATE


def test_normal_sdr_pixels_are_converted_to_bt709_not_only_tagged(final_outputs):
    outputs, expected, pcm = final_outputs
    path, _ = outputs[False]
    actual = decode_picture(path)
    assert actual.shape == expected.shape
    difference = np.abs(
        patch_interiors(actual).astype(np.int16)
        - patch_interiors(expected).astype(np.int16)
    )
    assert difference.mean() < 2
    assert np.max(difference.mean(axis=(0, 2, 3, 4))) < 3
    decoded = decode_audio(path, "f32le")
    # AAC's final codec packet may pad beyond the exact finite MP4 track duration.
    assert len(pcm) <= len(decoded) < len(pcm) + 1024
    expected_audio = pcm.astype(np.float64) / (2**31)
    actual_audio = decoded[: len(pcm)]
    # Lossy AAC can have isolated startup transients. Bound RMS error and
    # channel correlation while requiring its compensated sample origin exactly.
    error = np.sqrt(np.mean((actual_audio - expected_audio) ** 2, axis=0))
    level = np.sqrt(np.mean(expected_audio**2, axis=0))
    assert np.all(error / level < 0.08)
    for channel in range(2):
        assert (
            np.corrcoef(actual_audio[:, channel], expected_audio[:, channel])[0, 1]
            > 0.995
        )
        assert best_audio_lag(actual_audio[:, channel], expected_audio[:, channel]) == 0


def test_conformance_final_encode_preserves_exact_bgra_and_pcm(final_outputs):
    outputs, expected, pcm = final_outputs
    path, media = outputs[True]
    video, audio = media["streams"]
    assert video["codec_name"] == "ffv1" and video["pix_fmt"] == "bgra"
    assert (video["width"], video["height"]) == (WIDTH, HEIGHT)
    assert Fraction(video["r_frame_rate"]) == FPS
    assert int(video["nb_read_frames"]) == COUNT
    assert audio["codec_name"] == "pcm_s32le"
    assert int(audio["sample_rate"]) == RATE and audio["channels"] == 2
    assert np.array_equal(decode_picture(path), expected)
    assert np.array_equal(decode_audio(path, "s32le"), pcm)
