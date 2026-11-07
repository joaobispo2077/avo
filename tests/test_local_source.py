from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from avo.adapters.media import local_source
from avo.adapters.media.ffprobe import FfprobeMediaAdapter

NATIVE = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Actual FFmpeg/FFprobe required",
)


@pytest.mark.parametrize(
    "path",
    [
        "https://example.invalid/raw.mov",
        "file:///tmp/raw.mov",
        "concat:first.ts|second.ts",
        "pipe:0",
        "crypto:raw.mov",
        r"\\server\share\raw.mov",
        "//server/share/raw.mov",
        "-",
        "",
        "bad\x00name.mov",
    ],
)
def test_input_policy_rejects_protocol_network_and_stdin_before_opening(path):
    with pytest.raises(ValueError, match="local"):
        local_source.local_source_arguments(path)


@pytest.mark.parametrize(
    "path",
    [
        Path("local-original.mov"),
        Path("literal-%04d.mov"),
        r"C:\media\original.mov",
        "/mnt/c/media/original.mov",
    ],
)
def test_input_policy_is_closed_and_preserves_native_path_identity(path):
    arguments = local_source.local_source_arguments(path)
    assert arguments[arguments.index("-protocol_whitelist") + 1] == "file"
    formats = set(arguments[arguments.index("-format_whitelist") + 1].split(","))
    assert {"mov", "matroska", "wav"} <= formats
    assert not formats & {
        "hls",
        "dash",
        "concat",
        "imf",
        "avisynth",
        "rtsp",
        "sdp",
        "image2",
    }
    assert arguments[arguments.index("-max_streams") + 1] == "64"
    assert str(path) not in arguments


def test_only_explicit_literal_still_enables_image2_with_sequence_expansion_disabled():
    arguments = local_source.local_source_arguments(
        "literal-%04d.png", literal_still=True
    )
    assert arguments[arguments.index("-f") + 1] == "image2"
    assert arguments[arguments.index("-pattern_type") + 1] == "none"
    assert "image2" in arguments[arguments.index("-format_whitelist") + 1].split(",")


def _recording(path, *, container):
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["ffmpeg", "-v", "error", "-nostdin"]
    if container != "wav":
        args.extend(["-f", "lavfi", "-i", "color=red:s=32x32:r=24:d=1"])
    args.extend(
        ["-f", "lavfi", "-i", "sine=frequency=997:sample_rate=48000:duration=1"]
    )
    if container == "mpegts":
        args.extend(["-c:v", "mpeg2video", "-c:a", "mp2", "-f", "mpegts"])
    elif container == "mp4":
        args.extend(["-c:v", "libx264", "-c:a", "aac"])
    elif container != "wav":
        args.extend(
            ["-c:v", "png" if container == "mov" else "ffv1", "-c:a", "pcm_s16le"]
        )
    else:
        args.extend(["-c:a", "pcm_s16le"])
    subprocess.run([*args, str(path)], capture_output=True, check=True)


def _playlist(path, target):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1.0,\n"
        + target
        + "\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )


@NATIVE
@pytest.mark.parametrize("suffix", [".m3u8", ".mov"])
def test_inventory_rejects_hls_before_following_outside_root_segment(tmp_path, suffix):
    outside = tmp_path / "private" / "secret.ts"
    _recording(outside, container="mpegts")
    playlist = tmp_path / "declared" / ("handoff" + suffix)
    _playlist(playlist, "../private/secret.ts")
    with pytest.raises(subprocess.CalledProcessError) as error:
        FfprobeMediaAdapter().inventory([playlist])
    message = error.value.stderr.lower()
    if suffix == ".m3u8":
        assert "not on whitelist" in message
        assert "hls" in message
    assert outside.name not in message


@NATIVE
@pytest.mark.parametrize(
    "target",
    [
        "file:///definitely-outside-root/never-read.ts",
        "https://example.invalid/never-read.ts",
    ],
)
def test_native_format_rejection_precedes_playlist_header_and_external_url_open(
    tmp_path, target
):
    playlist = tmp_path / "declared" / "looks-like-original.mov"
    _playlist(playlist, target)
    # Force the disguised header's format independently of filename-probe heuristics.
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "debug",
            *local_source.local_source_arguments(playlist),
            "-f",
            "hls",
            "-show_streams",
            "-of",
            "json",
            "-i",
            str(playlist),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "not on whitelist" in result.stderr.lower()
    assert target not in result.stderr
    assert "never-read.ts" not in result.stderr
    assert not json.loads(result.stdout).get("streams")


@NATIVE
@pytest.mark.parametrize("extension", ["mov", "mp4", "mkv", "avi", "wav", "ts"])
def test_closed_policy_keeps_native_self_contained_originals_working(
    tmp_path, extension
):
    path = tmp_path / ("original." + extension)
    _recording(path, container="mpegts" if extension == "ts" else extension)
    source = FfprobeMediaAdapter().inventory([path])["sources"][0]
    assert source["durationSeconds"] > 0
    assert source["streams"]["audio"]
    assert bool(source["streams"]["video"]) == (extension != "wav")


@NATIVE
@pytest.mark.parametrize("extension", ["png", "jpg", "bmp", "tiff", "webp"])
def test_closed_policy_keeps_literal_static_images_without_sequence_reads(
    tmp_path, extension
):
    path = tmp_path / f"literal-%04d.{extension}"
    Image.new("RGB", (16, 16), (30, 90, 150)).save(path)
    source = FfprobeMediaAdapter().inventory([path])["sources"][0]
    assert source["streams"]["video"][0]["width"] == 16
    assert source["streams"]["audio"] == []


@NATIVE
def test_inventory_does_not_export_opaque_format_or_stream_metadata(
    tmp_path, monkeypatch
):
    path = tmp_path / "tagged.mkv"
    _recording(path, container="mkv")
    original = subprocess.run
    calls = []

    def observe(args, **kwargs):
        result = original(args, **kwargs)
        if args[0] == "ffprobe":
            calls.append((args, json.loads(result.stdout)))
        return result

    monkeypatch.setattr(subprocess, "run", observe)
    FfprobeMediaAdapter().inventory([path])
    args, raw = calls[0]
    assert "-show_entries" in args
    assert "-show_streams" not in args and "-show_format" not in args
    assert set(raw["format"]) == {"duration"}
    assert all(
        not set(stream.get("tags", {})) - {"DURATION"} for stream in raw["streams"]
    )


@NATIVE
def test_generic_image_pipe_detection_is_content_based_and_single_file(tmp_path):
    path = tmp_path / "standalone-image.bin"
    Image.new("RGB", (16, 16), (30, 90, 150)).save(path, format="PNG")
    source = FfprobeMediaAdapter().inventory([path])["sources"][0]
    assert source["streams"]["video"][0]["codecName"] == "png"
    assert source["streams"]["video"][0]["width"] == 16


@NATIVE
def test_native_stream_limit_rejects_container_with_more_than_64_streams(tmp_path):
    path = tmp_path / "many-streams.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=8000:cl=mono",
            "-t",
            "0.02",
            *[argument for _ in range(65) for argument in ("-map", "0:a:0")],
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        capture_output=True,
        check=True,
    )
    with pytest.raises(subprocess.CalledProcessError) as error:
        FfprobeMediaAdapter().inventory([path])
    assert "max_streams" in error.value.stderr
