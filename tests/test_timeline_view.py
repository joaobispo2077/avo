import json
import subprocess
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from numpy.testing import assert_allclose, assert_array_equal
from PIL import Image

from avo import timeline_view as view


@pytest.mark.parametrize(
    "count,times", [(0, ["4.000"]), (1, ["4.000"]), (3, ["2.000", "4.000", "6.000"])]
)
def test_frame_samples_include_endpoints_or_midpoint(
    tmp_path, monkeypatch, count, times
):
    run = Mock()
    monkeypatch.setattr(view.subprocess, "run", run)
    paths = view.extract_frames(Path("source.mp4"), 2, 6, count, tmp_path / "frames")
    assert [c.args[0][3] for c in run.call_args_list] == times
    assert paths == [tmp_path / "frames" / f"f_{i:03d}.jpg" for i in range(len(times))]
    for call, output in zip(run.call_args_list, paths, strict=True):
        assert call.args[0][-1] == str(output)
        assert call.args[0][-2] == "scale=320:-2"
        assert call.kwargs == {
            "check": True,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }


@pytest.mark.parametrize(
    "pcm,expected",
    [
        ([0, 8192, 16384], [0, 0.5, 1, 0]),
        ([16384] * 9, [1, 1, 1, 1]),
        ([0] * 8, [0, 0, 0, 0]),
        ([], [0, 0, 0, 0]),
    ],
)
def test_audio_envelope_rms_padding_and_normalization(monkeypatch, pcm, expected):
    outputs = []

    def decode(cmd, **kwargs):
        path = Path(cmd[-1])
        outputs.append(path)
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(np.asarray(pcm, dtype=np.int16).tobytes())
        assert cmd[3] == "1.000" and cmd[7] == "2.000"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(view.subprocess, "run", decode)
    assert_allclose(view.compute_envelope(Path("source"), 1, 3, samples=4), expected)
    assert not outputs[0].exists()


@pytest.mark.parametrize("failure", ["error", "empty", "missing", "raises"])
def test_envelope_cleanup_on_decoder_failure(monkeypatch, failure):
    outputs = []

    def decode(cmd, **kwargs):
        output = Path(cmd[-1])
        outputs.append(output)
        if failure == "missing":
            output.unlink()
        if failure == "raises":
            raise OSError("decoder missing")
        return SimpleNamespace(returncode=1 if failure == "error" else 0)

    monkeypatch.setattr(view.subprocess, "run", decode)
    if failure == "raises":
        with pytest.raises(OSError, match="decoder missing"):
            view.compute_envelope(Path("source"), 0, 1, samples=4)
    else:
        assert_array_equal(
            view.compute_envelope(Path("source"), 0, 1, samples=4), np.zeros(4)
        )
    assert not outputs[0].exists()


def test_word_boundaries_and_silences(tmp_path):
    transcript = tmp_path / "words.json"
    assert view.words_in_range(transcript, 1, 4) == []
    words = [
        {"start": 0, "end": 1},
        {"start": 4, "end": 5},
        {"start": None, "end": 2},
        {"start": 1.5, "end": 2, "type": "word", "text": "first"},
        {"start": 2, "end": 2.5, "type": "spacing"},
        {"start": 3, "end": 3.5, "type": "word", "text": "last"},
    ]
    transcript.write_text(json.dumps({"words": words}), encoding="utf-8")
    kept = view.words_in_range(transcript, 1, 4)
    assert kept == words[3:]
    assert view.find_silences(kept, 1, 4) == [(1, 1.5), (2, 3), (3.5, 4)]
    assert (
        view.find_silences([{"start": -1, "end": 2}, {"start": 1, "end": 1.5}], 0, 2)
        == []
    )


def test_font_load_falls_back_after_invalid_candidate(tmp_path, monkeypatch):
    invalid = tmp_path / "invalid.ttf"
    valid = tmp_path / "valid.ttf"
    invalid.touch()
    valid.touch()
    fallback = object()
    load = Mock(side_effect=[OSError("invalid font"), fallback])
    monkeypatch.setattr(
        view,
        "FONT_CANDIDATES",
        [str(tmp_path / "missing.ttf"), str(invalid), str(valid)],
    )
    monkeypatch.setattr(view.ImageFont, "truetype", load)
    assert view.load_font(14) is fallback
    assert load.call_args.args == (str(valid), 14)
    monkeypatch.setattr(view, "FONT_CANDIDATES", [])
    monkeypatch.setattr(view.ImageFont, "load_default", lambda: fallback)
    assert view.load_font(12) is fallback


@pytest.mark.parametrize("with_transcript", [False, True])
def test_rendered_timeline_contains_frames_waveform_and_annotations(
    tmp_path, monkeypatch, with_transcript
):
    def frames(video, start, end, count, dest):
        paths = [dest / "red.png", dest / "green.png"]
        for path, color in zip(paths, [(240, 0, 0), (0, 240, 0)], strict=True):
            Image.new("RGB", (320, 180), color).save(path)
        return paths

    monkeypatch.setattr(view, "extract_frames", frames)
    monkeypatch.setattr(
        view, "compute_envelope", lambda *args, **kwargs: np.ones(400) * 0.5
    )
    transcript = tmp_path / "words.json"
    transcript.write_text(
        json.dumps(
            {
                "words": [
                    {"start": 1, "end": 1.5, "type": "word", "text": "hello"},
                    {"start": 1.51, "end": 1.6, "type": "word", "text": "near"},
                    {"start": 1.7, "end": 1.71, "type": "word", "text": "short"},
                    {"start": 2, "end": 2.1, "type": "spacing"},
                    {"start": 2.4, "end": 2.5, "type": "word", "text": ""},
                ]
            }
        )
    )
    output = tmp_path / "nested" / "view.png"
    view.render_timeline(
        Path("source.mp4"), 0, 3, output, 2, transcript if with_transcript else None
    )
    with Image.open(output) as image:
        assert image.size == (1920, 540)
        assert image.getpixel((100, 100)) == (240, 0, 0)
        assert image.getpixel((400, 100)) == (0, 240, 0)
        assert image.getpixel((100, 300)) != view.BG
    assert json.loads(transcript.read_text())["words"][0]["text"] == "hello"


@pytest.mark.parametrize(
    "argv,message",
    [
        ([], "required"),
        (["--edl", "edl.json"], "not implemented"),
        (["missing.mp4", "0", "1"], "video not found"),
    ],
)
def test_timeline_cli_rejects_invalid_inputs(monkeypatch, capsys, argv, message):
    monkeypatch.setattr(sys, "argv", ["timeline-view", *argv])
    with pytest.raises(SystemExit) as exc:
        view.main()
    assert message in str(exc.value) + capsys.readouterr().err


def test_timeline_cli_auto_transcript_and_output(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    transcript = tmp_path / "edit" / "transcripts" / "source.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}")
    render = Mock()
    monkeypatch.setattr(view, "render_timeline", render)
    monkeypatch.setattr(
        sys, "argv", ["timeline-view", str(source), "1", "3", "--n-frames", "4"]
    )
    view.main()
    render.assert_called_once_with(
        video=source,
        start=1,
        end=3,
        out_path=tmp_path / "edit" / "verify" / "source_1.00-3.00.png",
        n_frames=4,
        transcript=transcript,
    )
    monkeypatch.setattr(sys, "argv", ["timeline-view", str(source), "3", "1"])
    with pytest.raises(SystemExit, match="end must be > start"):
        view.main()
