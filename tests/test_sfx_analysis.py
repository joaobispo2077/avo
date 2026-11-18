"""Actual native PCM measurement remains descriptive, never human approval."""

import hashlib
import wave

import numpy as np
import pytest

from avo.adapters.media.sfx_analysis import SfxAnalyzer


def source(tmp_path, *, rate=48000, seconds=1, silence=False):
    samples = np.zeros((int(rate * seconds), 2), dtype="<i2")
    if not silence:
        width = rate // 20
        tone = (12000 * np.sin(2 * np.pi * 3000 * np.arange(width) / rate)).astype(
            "<i2"
        )
        samples[rate // 10 : rate // 10 + width, 0] = tone
        samples[rate // 2 : rate // 2 + width, 1] = tone
    path = tmp_path / "attacks.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_actual_native_channels_onsets_centroid_and_no_approval(tmp_path):
    path, sha = source(tmp_path)
    facts = SfxAnalyzer()(path, source_sha256=sha)
    assert facts["sourceSha256"] == sha
    assert facts["sampleRate"] == 48000
    assert facts["channels"] == 2
    assert facts["sourceSamples"] == 48000
    assert facts["coverage"] == "complete"
    assert len(facts["onsets"]) == 2
    assert facts["usefulRange"]["startSample"] >= 4800
    assert facts["usefulRange"]["endSampleExclusive"] <= 26401
    assert 2800 < facts["spectralCentroidHz"] < 3200
    assert 0 < facts["rms"] < facts["peak"] < 1
    assert facts["silence"] is False
    assert not {"status", "approved", "reviewed", "material", "rights"} & facts.keys()


def test_silence_and_decode_budget_are_honest(tmp_path):
    path, sha = source(tmp_path, silence=True)
    facts = SfxAnalyzer()(path, source_sha256=sha)
    assert facts["silence"] is True
    assert facts["onsets"] == []
    assert facts["spectralCentroidHz"] is None
    path, sha = source(tmp_path, seconds=2)
    limited = SfxAnalyzer(max_seconds=0.25)(path, source_sha256=sha)
    assert limited["coverage"] == "partial"
    assert limited["analyzedSamples"] <= 12000
    assert limited["sourceSamples"] == 96000
    assert limited["analyzer"]["maxSeconds"] == 0.25


def test_decoder_rejects_protocols_and_bad_limits(tmp_path):
    with pytest.raises(ValueError):
        SfxAnalyzer()("https://invalid.example/sound.wav", source_sha256="a" * 64)
    with pytest.raises(ValueError):
        SfxAnalyzer(max_seconds=float("inf"))


def test_many_attacks_disclose_bounded_onset_list_coverage():
    from avo.adapters.media.sfx_analysis import _facts

    samples = np.zeros((48000, 1))
    samples[::96, 0] = 0.5
    facts = _facts(samples, 48000)
    assert len(facts["onsets"]) == 256
    assert facts["onsetCount"] == 500
    assert facts["onsetCoverage"] == "partial"
