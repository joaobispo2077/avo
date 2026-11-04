from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from avo.adapters.media.ffprobe import INVENTORY_ENTRIES, FfprobeMediaAdapter
from avo.adapters.media.local_source import local_source_arguments


def _inventory(monkeypatch, tmp_path, probe):
    path = tmp_path / "source.mkv"
    path.write_bytes(b"source")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=json.dumps(probe))

    monkeypatch.setattr(subprocess, "run", run)
    source = FfprobeMediaAdapter().inventory([path])["sources"][0]
    return source, calls


@pytest.mark.parametrize(
    "name,image",
    [
        ("literal-%d.png", True),
        ("literal-%04d.JPG", True),
        ("source.jpeg", True),
        ("source.bmp", True),
        ("source.tif", True),
        ("source.tiff", True),
        ("source.webp", True),
        ("take.mov", False),
    ],
)
def test_inventory_uses_literal_image_input_without_granting_still_admission(
    monkeypatch, tmp_path, name, image
):
    path = tmp_path / name
    path.write_bytes(b"unverified inventory input")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=json.dumps({"streams": []}))

    monkeypatch.setattr(subprocess, "run", run)
    source = FfprobeMediaAdapter().inventory([path])["sources"][0]
    expected = [
        "ffprobe",
        "-v",
        "error",
        *local_source_arguments(path, literal_still=image),
    ]
    expected.extend(
        ["-show_entries", INVENTORY_ENTRIES, "-of", "json", "-i", str(path)]
    )
    assert calls == [expected]
    assert source["streams"] == {"video": [], "audio": []}


def test_inventory_preserves_exact_stream_timing_and_audio_layout(
    monkeypatch, tmp_path
):
    source, calls = _inventory(
        monkeypatch,
        tmp_path,
        {
            "format": {"duration": "100.1"},
            "streams": [
                {
                    "index": 2,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30000/1001",
                    "avg_frame_rate": "29999/1001",
                    "time_base": "1/30000",
                    "duration_ts": 3003000,
                    "duration": "100.1",
                },
                {
                    "index": 3,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 6,
                    "channel_layout": "5.1(side)",
                    "time_base": "1/48000",
                    "duration_ts": 4804800,
                    "duration": "100.1",
                },
            ],
        },
    )
    assert source["durationSeconds"] == 100.1
    assert source["streams"]["video"] == [
        {
            "index": 2,
            "codec": "h264",
            "codecName": "h264",
            "frameCount": None,
            "sampleAspectRatio": None,
            "width": 1920,
            "height": 1080,
            "timeBase": "1/30000",
            "frameRate": "30000/1001",
            "averageFrameRate": "29999/1001",
            "durationTicks": 3003000,
            "durationSeconds": 100.1,
            "startTicks": None,
            "startTimeSeconds": None,
        }
    ]
    assert source["streams"]["audio"] == [
        {
            "index": 3,
            "codec": "aac",
            "sampleRate": 48000,
            "channels": 6,
            "channelLayout": "5.1(side)",
            "timeBase": "1/48000",
            "durationTicks": 4804800,
            "durationSeconds": 100.1,
            "startTicks": None,
            "startTimeSeconds": None,
        }
    ]
    assert calls[0][1] == {
        "check": True,
        "capture_output": True,
        "text": True,
        "timeout": 60,
    }


@pytest.mark.parametrize("rate", [None, "0/0"])
@pytest.mark.parametrize("duration", [None, "", "N/A"])
def test_missing_stream_properties_stay_unknown_without_format_fallback(
    monkeypatch, tmp_path, rate, duration
):
    source, _ = _inventory(
        monkeypatch,
        tmp_path,
        {
            "format": {"duration": "120.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "r_frame_rate": rate,
                    "duration": duration,
                    "duration_ts": duration,
                },
                {
                    "codec_type": "audio",
                    "duration": duration,
                    "duration_ts": duration,
                },
            ],
        },
    )
    video = source["streams"]["video"][0]
    audio = source["streams"]["audio"][0]
    assert video["frameRate"] == (rate or "")
    assert video["averageFrameRate"] == ""
    assert audio["channelLayout"] == ""
    for stream in (video, audio):
        assert stream["durationTicks"] is None
        assert stream["durationSeconds"] is None
        assert stream["timeBase"] == ""
    assert source["durationSeconds"] == 120.5


@pytest.mark.parametrize("duration", [None, "", "N/A"])
def test_matroska_tag_bounds_each_stream_without_format_fallback(
    monkeypatch, tmp_path, duration
):
    source, _ = _inventory(
        monkeypatch,
        tmp_path,
        {
            "format": {"duration": "60"},
            "streams": [
                {
                    "codec_type": "video",
                    "duration": duration,
                    "tags": {"DURATION": "00:00:03.000000000"},
                },
                {
                    "codec_type": "audio",
                    "duration": duration,
                    "tags": {"DURATION": "00:00:01.250000000"},
                },
            ],
        },
    )
    assert source["streams"]["video"][0]["durationSeconds"] == 3.0
    assert source["streams"]["audio"][0]["durationSeconds"] == 1.25
    assert source["durationSeconds"] == 60.0


@pytest.mark.parametrize("duration", ["0", "2.5"])
def test_explicit_stream_duration_precedes_matroska_tag(
    monkeypatch, tmp_path, duration
):
    source, _ = _inventory(
        monkeypatch,
        tmp_path,
        {
            "streams": [
                {
                    "codec_type": "audio",
                    "duration": duration,
                    "tags": {"DURATION": "00:00:09.000000000"},
                }
            ]
        },
    )
    assert source["streams"]["audio"][0]["durationSeconds"] == float(duration)


@pytest.mark.parametrize(
    "tag,expected",
    [("01:02:03.123456789", 3723.123456789), ("00:00:00.000000000", 0.0)],
)
def test_matroska_tag_preserves_hours_minutes_and_fraction(
    monkeypatch, tmp_path, tag, expected
):
    source, _ = _inventory(
        monkeypatch,
        tmp_path,
        {"streams": [{"codec_type": "audio", "tags": {"DURATION": tag}}]},
    )
    assert source["streams"]["audio"][0]["durationSeconds"] == expected


@pytest.mark.parametrize(
    "tag",
    [
        None,
        "",
        "N/A",
        "NaN",
        "Infinity",
        "00:00:nan",
        "00:00:inf",
        "00:00:03",
        "0:00:03.000000000",
        "00:60:03.000000000",
        "00:00:60.000000000",
        "-1:00:03.000000000",
        "00:00:03.0000000000",
        "00:00:03.000000000 trailing",
        "00:00:03.000000000\n",
        pytest.param("9" * 10000, id="oversized"),
        3,
    ],
)
def test_unknown_matroska_tag_never_infers_format_duration(monkeypatch, tmp_path, tag):
    source, _ = _inventory(
        monkeypatch,
        tmp_path,
        {
            "format": {"duration": "60"},
            "streams": [{"codec_type": "audio", "tags": {"DURATION": tag}}],
        },
    )
    assert source["streams"]["audio"][0]["durationSeconds"] is None


@pytest.mark.parametrize("codec", ["video", "audio"])
@pytest.mark.parametrize(
    "ticks,seconds,expected_ticks,expected_seconds",
    [
        (None, None, None, None),
        ("N/A", "N/A", None, None),
        (0, "0.0", 0, 0.0),
        (90000, "3.0", 90000, 3.0),
    ],
)
def test_stream_origins_preserve_probe_clocks_without_format_fallback(
    monkeypatch, tmp_path, codec, ticks, seconds, expected_ticks, expected_seconds
):
    source, _ = _inventory(
        monkeypatch,
        tmp_path,
        {
            "format": {"start_time": "99"},
            "streams": [
                {"codec_type": codec, "start_pts": ticks, "start_time": seconds}
            ],
        },
    )
    stream = source["streams"][codec][0]
    assert stream["startTicks"] == expected_ticks
    assert stream["startTimeSeconds"] == expected_seconds
