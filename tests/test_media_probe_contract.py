import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo import render, voiceover
from avo.adapters.media.ffprobe import audio_sample_rate


@pytest.mark.parametrize("probe", [render.media_duration, voiceover.media_duration])
@pytest.mark.parametrize("stdout,expected", [("12.5\n", 12.5), ("invalid", None)])
def test_duration_probe_retains_command_and_best_effort_result(
    monkeypatch, probe, stdout, expected
):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(subprocess, "run", run)
    assert probe(Path("source.mkv")) == expected
    assert calls == [
        (
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                "source.mkv",
            ],
            {"capture_output": True, "text": True, "check": True},
        )
    ]


@pytest.mark.parametrize("probe", [render.media_duration, voiceover.media_duration])
def test_duration_probe_returns_none_for_tool_failure(monkeypatch, probe):
    def fail(*args, **kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(subprocess, "run", fail)
    assert probe(Path("source.mkv")) is None


@pytest.mark.parametrize("codec", ["audio", "video"])
def test_sample_rate_probe_selects_exact_stream_and_rejects_video(monkeypatch, codec):
    import json

    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "streams": [
                        {"index": 0, "codec_type": "audio", "sample_rate": "48000"},
                        {"index": 2, "codec_type": codec, "sample_rate": "44100"},
                    ]
                }
            )
        )

    monkeypatch.setattr(subprocess, "run", run)
    if codec == "audio":
        assert audio_sample_rate({"streamIndex": 2}, Path("source.mkv")) == 44100
    else:
        with pytest.raises(ValueError, match="selected stream must contain audio"):
            audio_sample_rate({"streamIndex": 2}, Path("source.mkv"))
    assert calls == [
        (
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", "source.mkv"],
            {"capture_output": True, "text": True, "check": True},
        )
    ]
