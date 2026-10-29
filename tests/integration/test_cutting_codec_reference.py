"""Lossy encoding belongs in the source reference, never in relaxed thresholds."""

import shutil
import subprocess
from copy import deepcopy

import numpy as np
import pytest
from scipy.io import wavfile

from avo.adapters.media.cutting_audio import read_pcm
from avo.adapters.media.cutting_preview import CuttingPreviewAdapter
from avo.adapters.media.proof_executor import PROOF_AUDIO_BITRATE
from avo.adapters.qc.cutting_boundary import _reference_audio, compare_retained_signal
from avo.transcribe import source_fingerprint


def _entry(source, rate):
    return {
        "source": source,
        "selection": {"streamIndex": 0, "channels": [0]},
        "source_range": {
            "sourceId": "s1",
            "startTicks": 0,
            "endTicksExclusive": rate,
            "timebase": {"num": 1, "den": rate},
        },
        "fingerprint": source_fingerprint(source),
        "sync_ref": {"locator": "sync.json", "sha256": "a" * 64},
        "processing": {
            "recipe": "native-dialogue-v1",
            "node": {
                "sourceRange": {"startSample": 0, "endSampleExclusive": rate},
                "outputRange": {"startSample": 0, "endSampleExclusive": rate},
                "sourceSampleRate": rate,
                "targetSampleRate": rate,
                "channelMap": [0, 0],
            },
            "dialogueNoiseReductionPolicy": None,
            "fadeSamples": [0, 0],
            "windowOffsetSamples": 0,
            "windowLengthSamples": rate,
        },
    }


def _encoding():
    return {
        "codec": "aac",
        "sampleRate": 48000,
        "channelLayout": "dual-mono",
        "bitrate": PROOF_AUDIO_BITRATE,
    }


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
@pytest.mark.parametrize("missing", [None, "onset", "tail"])
def test_encoded_reference_preserves_detection_of_missing_quiet_edges(
    tmp_path, missing
):
    rate = 48000
    clock = np.arange(rate) / rate
    # Quiet consonant-like noise on both sides of a voiced synthetic unit.
    signal = np.sin(clock * 2 * np.pi * 180) * 0.2
    noise = np.random.default_rng(4).normal(0, 0.003, rate)
    signal[: round(rate * 0.16)] = noise[: round(rate * 0.16)]
    signal[round(rate * 0.84) :] = noise[round(rate * 0.84) :]
    original = tmp_path / "original.wav"
    wavfile.write(original, rate, (signal * 2**31).astype("int32"))
    expected = _reference_audio(_entry(original, rate), tmp_path / "ref", _encoding())
    candidate_signal = signal.copy()
    if missing == "onset":
        candidate_signal[round(rate * 0.09) : round(rate * 0.14)] = 0
    if missing == "tail":
        candidate_signal[round(rate * 0.86) : round(rate * 0.91)] = 0
    wav = tmp_path / "candidate.wav"
    wavfile.write(wav, rate, (candidate_signal * 2**31).astype("int32"))
    encoded, decoded = tmp_path / "candidate.m4a", tmp_path / "decoded.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(wav),
            "-af",
            "pan=stereo|c0=c0|c1=c0",
            "-c:a",
            "aac",
            "-b:a",
            PROOF_AUDIO_BITRATE,
            str(encoded),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(encoded),
            "-af",
            "atrim=end_sample=48000,pan=mono|c0=c0,aresample=16000",
            "-c:a",
            "pcm_s16le",
            str(decoded),
        ],
        check=True,
    )
    actual = read_pcm(decoded)[0][:, 0]
    result = compare_retained_signal(
        expected,
        actual,
        16000,
        [{"text": "synthetic", "start": 0.1, "end": 0.9, "observed": True}],
    )
    assert result["status"] == ("pass" if missing is None else "fail")
    if missing:
        assert any(
            c["kind"] == missing and c["status"] == "fail" for c in result["checks"]
        )


@pytest.mark.parametrize("invalid", ["bitrate", "channels", "legacy"])
def test_unknown_codec_reference_contract_is_rejected(tmp_path, invalid, monkeypatch):
    from avo.adapters.qc import cutting_boundary as boundary

    source = tmp_path / "source.wav"
    wavfile.write(source, 48000, np.zeros(48000, dtype="int32"))
    entry, encoding = _entry(source, 48000), _encoding()
    monkeypatch.setattr(boundary, "_native_reference", lambda *_: np.ones(48000) * 0.1)
    (tmp_path / "ref").mkdir()
    if invalid == "bitrate":
        encoding["bitrate"] = "128k"
    elif invalid == "channels":
        entry["processing"]["node"]["channelMap"] = [0, 1]
    else:
        del entry["processing"]
    with pytest.raises(ValueError, match="reference"):
        _reference_audio(entry, tmp_path / "ref", encoding)


def test_preview_reference_encoding_comes_from_declared_plan_and_routing():
    plan = {
        "output": {
            "audioCodec": "aac",
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
        }
    }
    maps = [{"node": {"channelMap": [0, 0]}}]
    assert CuttingPreviewAdapter._reference_encoding(plan, maps) == _encoding()
    for field, value in (("conformance", True), ("audioCodec", "pcm_s32le")):
        changed = deepcopy(plan)
        changed["output"][field] = value
        assert CuttingPreviewAdapter._reference_encoding(changed, maps) is None
    maps[0]["node"]["channelMap"] = [0, 1]
    assert CuttingPreviewAdapter._reference_encoding(plan, maps) is None
