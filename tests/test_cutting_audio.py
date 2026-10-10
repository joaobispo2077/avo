"""Routed audio extraction is evidence, never an implicit default stream."""

import shutil
import wave

import numpy as np
import pytest

from avo.adapters.media.cutting_acoustics import (
    analyze_waveform,
    pause_candidates,
    speech_probability_ranges,
)
from avo.adapters.media.cutting_audio import extract_dialogue_pcm
from avo.timeline.ports import ToolError
from avo.transcribe import source_fingerprint


def make_wave(path, channels, rate=48000):
    samples = np.asarray(channels, dtype=np.float64)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(samples.shape[1])
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes((samples * 32000).astype("<i2").tobytes())
    return path


def request(path, output):
    return {
        "selection": {"streamIndex": 0, "channels": [0], "sourceLayout": "mono"},
        "source_range": {
            "sourceId": "s1",
            "startTicks": 0,
            "endTicksExclusive": 1000,
            "timebase": {"num": 1, "den": 1000},
        },
        "fingerprint": source_fingerprint(path),
        "sync_ref": {"sha256": "a" * 64},
        "output_dir": output,
    }


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_extract_explicit_channel_preserves_native_rate(tmp_path):
    tone = np.sin(np.arange(48000) * 2 * np.pi * 440 / 48000) * 0.2
    path = make_wave(
        tmp_path / "source.wav", np.stack([tone, np.zeros_like(tone)], axis=1)
    )
    result = extract_dialogue_pcm(path, **request(path, tmp_path / "output"))
    assert result["sampleRate"] == 48000
    assert result["channels"] == [0]
    with wave.open(result["analysisPath"]) as stream:
        assert stream.getframerate() == 16000
        assert stream.getnchannels() == 1


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_invalid_stream_or_channel_fails_not_silence(tmp_path):
    path = make_wave(tmp_path / "source.wav", np.zeros((48000, 1)))
    args = request(path, tmp_path / "out")
    args["selection"]["streamIndex"] = 1
    with pytest.raises(ToolError, match="routing"):
        extract_dialogue_pcm(path, **args)
    args["selection"] = {"streamIndex": 0, "channels": [1]}
    with pytest.raises(ToolError, match="routing"):
        extract_dialogue_pcm(path, **args)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_phase_cancellation_is_unsafe(tmp_path):
    tone = np.sin(np.arange(48000) * 0.1) * 0.2
    path = make_wave(tmp_path / "source.wav", np.stack([tone, -tone], axis=1))
    args = request(path, tmp_path / "out")
    args["selection"]["channels"] = [0, 1]
    with pytest.raises(ToolError, match="cancellation"):
        extract_dialogue_pcm(path, **args)


def test_waveform_uses_10ms_windows_5ms_hop_and_source_clock(tmp_path):
    path = make_wave(tmp_path / "source.wav", np.ones((1600, 1)) * 0.01, rate=16000)
    evidence = analyze_waveform(path, source_start=10)
    assert evidence["windowMs"] == 10
    assert evidence["hopMs"] == 5
    assert evidence["frames"][0]["start"] == 10
    assert evidence["frames"][1]["start"] == 10.005
    assert evidence["frames"][0]["rms"] > 0


def test_missing_audio_is_error_not_zero_measurement(tmp_path):
    with pytest.raises(ToolError):
        analyze_waveform(tmp_path / "missing.wav")


def test_short_speech_probability_event_is_preserved():
    ranges = speech_probability_ranges(np.array([0, 0.9, 0]), source_start=2)
    assert ranges == [{"start": 2.032, "end": 2.064}]


def test_measured_quiet_tail_is_not_erased_by_early_word_estimate(tmp_path):
    # Explicit synthetic boundary evidence, not real CTC inference or language validation.
    rate = 16000
    audio = np.zeros(rate)
    audio[:4000] = 0.1
    audio[4000:5600] = np.sin(np.arange(1600) * 2 * np.pi * 3500 / rate) * 0.0008
    audio[12000:] = 0.1
    path = make_wave(tmp_path / "quiet-tail.wav", audio[:, None], rate=rate)
    measured = analyze_waveform(path)
    alignment = {
        "words": [
            {"text": "before", "start": 0, "end": 0.25, "eligibleEdge": True},
            {"text": "after", "start": 0.75, "end": 1, "eligibleEdge": True},
        ]
    }
    candidates = pause_candidates(alignment, measured, [], "s1")
    assert len(candidates) == 1
    assert candidates[0]["sourceRange"]["startTicks"] >= 350000
    assert candidates[0]["evidence"]["context"]["dispensable"] is None


def test_source_fingerprint_mismatch_rejected_before_decode(tmp_path):
    path = make_wave(tmp_path / "source.wav", np.zeros((48000, 1)))
    args = request(path, tmp_path / "out")
    args["fingerprint"]["sha256"] = "f" * 64
    with pytest.raises(ToolError, match="fingerprint"):
        extract_dialogue_pcm(path, **args)
