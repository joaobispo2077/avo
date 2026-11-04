import json
import shutil
import subprocess
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from PIL import Image

from avo.adapters.media.ffprobe import FfprobeMediaAdapter, _video_stream
from avo.adapters.media.still_probe import verify_literal_still


def _probe(monkeypatch, tmp_path, *, codec="png", frames="1", streams=None):
    path = tmp_path / "literal-%d.png"
    image_format = {"mjpeg": "JPEG", "bmp": "BMP", "tiff": "TIFF", "webp": "WEBP"}.get(
        codec, "PNG"
    )
    Image.new("RGB", (8, 8), "red").save(path, format=image_format)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "streams": streams
                    if streams is not None
                    else [
                        {
                            "codec_type": "video",
                            "codec_name": codec,
                            "nb_read_frames": frames,
                        }
                    ]
                }
            )
        )

    monkeypatch.setattr(subprocess, "run", run)
    return path, calls


def test_still_probe_treats_percent_filename_as_one_literal_input(
    monkeypatch, tmp_path
):
    path, calls = _probe(monkeypatch, tmp_path)
    assert verify_literal_still(path) == {"codecName": "png", "decodedFrameCount": 1}
    argv, options = calls[0]
    assert argv == [
        "ffprobe",
        "-v",
        "error",
        "-f",
        "image2",
        "-pattern_type",
        "none",
        "-count_frames",
        "-show_entries",
        "stream=codec_type,codec_name,nb_read_frames",
        "-of",
        "json",
        str(path),
    ]
    assert options == {
        "check": True,
        "capture_output": True,
        "text": True,
        "timeout": 30,
    }


@pytest.mark.parametrize("codec", ["png", "mjpeg", "bmp", "tiff", "webp"])
def test_still_probe_accepts_only_explicit_supported_decoded_codecs(
    monkeypatch, tmp_path, codec
):
    path, _ = _probe(monkeypatch, tmp_path, codec=codec)
    assert verify_literal_still(path)["codecName"] == codec


@pytest.mark.parametrize(
    "codec,frames",
    [
        ("h264", "1"),
        ("apng", "1"),
        ("png", "2"),
        ("png", "0"),
        ("png", None),
        ("png", "N/A"),
        ("png", "1.0"),
        ("png", True),
    ],
)
def test_still_probe_rejects_animation_video_and_unknown_frame_count(
    monkeypatch, tmp_path, codec, frames
):
    path, _ = _probe(monkeypatch, tmp_path, codec=codec, frames=frames)
    with pytest.raises(ValueError, match="still.*literal-%d.png"):
        verify_literal_still(path)


@pytest.mark.parametrize(
    "streams",
    [
        [],
        [{"codec_type": "audio"}],
        [{"codec_type": "video", "codec_name": "png", "nb_read_frames": "1"}] * 2,
    ],
)
def test_still_probe_requires_exactly_one_video_stream(monkeypatch, tmp_path, streams):
    path, _ = _probe(monkeypatch, tmp_path, streams=streams)
    with pytest.raises(ValueError, match="still"):
        verify_literal_still(path)


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("ffprobe"),
        subprocess.TimeoutExpired("ffprobe", 30),
        subprocess.CalledProcessError(1, "ffprobe", stderr="decode failed"),
    ],
)
def test_still_probe_wraps_tool_failures_with_input_scope(monkeypatch, tmp_path, error):
    path, _ = _probe(monkeypatch, tmp_path)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ValueError, match="still.*literal-%d.png"):
        verify_literal_still(path)


def test_still_probe_wraps_malformed_probe_response(monkeypatch, tmp_path):
    path, _ = _probe(monkeypatch, tmp_path)
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="not json")
    )
    with pytest.raises(ValueError, match="still.*literal-%d.png"):
        verify_literal_still(path)


@pytest.mark.parametrize("response", [None, [], "text"])
def test_still_probe_rejects_non_object_response(monkeypatch, tmp_path, response):
    path, _ = _probe(monkeypatch, tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(response)),
    )
    with pytest.raises(ValueError, match="still.*literal-%d.png"):
        verify_literal_still(path)


def test_still_probe_rejects_codec_disagreement_with_image_container(
    monkeypatch, tmp_path
):
    path, _ = _probe(monkeypatch, tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps(
                {
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "mjpeg",
                            "nb_read_frames": "1",
                        }
                    ]
                }
            )
        ),
    )
    with pytest.raises(ValueError, match="still.*literal-%d.png"):
        verify_literal_still(path)


@pytest.mark.parametrize("size", [(16385, 1), (8001, 8000)])
def test_still_probe_bounds_dimensions_before_decoder_allocation(
    monkeypatch, tmp_path, size
):
    path, calls = _probe(monkeypatch, tmp_path)
    image = SimpleNamespace(size=size, format="PNG", n_frames=1, is_animated=False)
    monkeypatch.setattr(Image, "open", lambda path: nullcontext(image))
    with pytest.raises(ValueError, match="still.*supported dimensions"):
        verify_literal_still(path)
    assert calls == []


@pytest.mark.parametrize(
    "error",
    [
        Image.DecompressionBombError("oversized"),
        Image.DecompressionBombWarning("oversized"),
    ],
)
def test_still_probe_wraps_image_bomb_failures(monkeypatch, tmp_path, error):
    path, calls = _probe(monkeypatch, tmp_path)

    def fail(path):
        raise error

    monkeypatch.setattr(Image, "open", fail)
    with pytest.raises(ValueError, match="still.*literal-%d.png"):
        verify_literal_still(path)
    assert calls == []


def test_still_probe_rejects_relative_missing_and_unsupported_paths(tmp_path):
    unsupported = tmp_path / "picture.gif"
    unsupported.write_bytes(b"uninspected")
    for path in (
        tmp_path.relative_to(tmp_path.anchor) / "picture.png",
        tmp_path / "missing.png",
        unsupported,
    ):
        with pytest.raises(ValueError, match="still"):
            verify_literal_still(path)


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="native ffprobe required")
def test_native_png_percent_filename_and_animated_png_are_distinguished(tmp_path):
    still = tmp_path / "literal-%d.png"
    first = Image.new("RGB", (8, 8), "red")
    first.save(still)
    inventory = FfprobeMediaAdapter().inventory([still])["sources"][0]
    assert inventory["locator"] == str(still)
    assert inventory["streams"]["video"][0]["codecName"] == "png"
    assert verify_literal_still(still) == {"codecName": "png", "decodedFrameCount": 1}
    animated = tmp_path / "animated.png"
    first.save(
        animated,
        save_all=True,
        append_images=[Image.new("RGB", (8, 8), "blue")],
        duration=100,
        loop=0,
    )
    with pytest.raises(ValueError, match="still.*animated.png"):
        verify_literal_still(animated)


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="native ffmpeg and ffprobe required",
)
def test_native_video_renamed_to_png_is_rejected(tmp_path):
    renamed = tmp_path / "renamed.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=8x8:r=24",
            "-frames:v",
            "2",
            "-c:v",
            "ffv1",
            "-f",
            "matroska",
            str(renamed),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with pytest.raises(ValueError, match="still.*renamed.png"):
        verify_literal_still(renamed)


def test_video_inventory_exposes_decoded_codec_and_declared_frame_count():
    stream = _video_stream({"codec_name": "png", "nb_frames": "1"})
    assert stream["codecName"] == "png"
    assert stream["frameCount"] == 1
    assert _video_stream({"nb_frames": "N/A"})["frameCount"] is None
