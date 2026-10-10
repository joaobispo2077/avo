"""Encoded signal checks expose a removed speech tail; a fade cannot restore it."""

import shutil
import subprocess
import wave

import numpy as np
import pytest

from avo.adapters.qc.cutting_boundary import (
    CuttingBoundaryVerifier,
    _reference_audio,
    compare_retained_signal,
)
from avo.timeline.cutting_contracts import make_document
from avo.transcribe import source_fingerprint


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_native_noise_reference_processes_full_node_before_window_crop(tmp_path):
    from scipy.io import wavfile

    rate = 48000
    clock = np.arange(rate * 2) / rate
    signal = np.sin(clock * 2 * np.pi * 180) * 0.25
    source = tmp_path / "raw.wav"
    wavfile.write(source, rate, (signal * 32767).astype("int16"))
    policy = {
        "mode": "afftdn",
        "role": "presenter-dialogue",
        "strengthPercent": 40,
        "streamIndex": 0,
        "channelIndex": 0,
        "approvedByUser": True,
    }
    node = {
        "sourceRange": {"startSample": 0, "endSampleExclusive": rate * 2},
        "outputRange": {"startSample": 0, "endSampleExclusive": rate * 2},
        "sourceSampleRate": rate,
        "targetSampleRate": rate,
        "channelMap": [0, 0],
    }
    entry = {
        "source": source,
        "selection": {"streamIndex": 0, "channels": [0]},
        "source_range": {
            "sourceId": "s1",
            "startTicks": 0,
            "endTicksExclusive": rate * 2,
            "timebase": {"num": 1, "den": rate},
        },
        "fingerprint": source_fingerprint(source),
        "sync_ref": {"locator": "sync.json", "sha256": "a" * 64},
        "processing": {
            "recipe": "native-dialogue-v1",
            "node": node,
            "dialogueNoiseReductionPolicy": policy,
            "fadeSamples": [0, 0],
            "windowOffsetSamples": rate,
            "windowLengthSamples": rate,
        },
    }
    actual = _reference_audio(entry, tmp_path / "references")
    expected = tmp_path / "expected.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-af",
            (
                "atrim=end_sample=96000,asetpts=PTS-STARTPTS,pan=mono|c0=c0,apad=pad_len=1200,"
                "afftdn=nr=9.33:nf=-34.0:tn=1,atrim=start_sample=1200,asetpts=N/SR/TB,"
                "pan=stereo|c0=c0|c1=c0,apad,atrim=end_sample=96000,"
                "atrim=start_sample=48000:end_sample=96000,asetpts=PTS-STARTPTS,"
                "pan=mono|c0=0.5*c0+0.5*c1,aresample=16000"
            ),
            "-c:a",
            "pcm_s16le",
            str(expected),
        ],
        check=True,
    )
    _, expected_pcm = wavfile.read(expected)
    assert len(actual) == 16000
    np.testing.assert_allclose(actual, expected_pcm.astype(float) / 32768, atol=1e-6)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_encoded_missing_tail_fails_and_restored_original_passes(tmp_path):
    # Synthetic voiced-signal fixture, not a claim of semantic speech recognition.
    rate = 16000
    t = np.arange(rate) / rate
    reference = np.sin(t * 2 * np.pi * 180) * 0.25 + np.sin(t * 2 * np.pi * 1100) * 0.08
    reference[:1600] = 0
    reference[14400:] = 0
    results = []
    for name, samples in (
        ("complete", reference.copy()),
        ("clipped", reference.copy()),
    ):
        if name == "clipped":
            samples[12800:14400] = 0
            samples[12320:12800] *= np.linspace(1, 0, 480)
        source, encoded, decoded = (
            tmp_path / f"{name}.wav",
            tmp_path / f"{name}.m4a",
            tmp_path / f"{name}-decoded.wav",
        )
        with wave.open(str(source), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(rate)
            stream.writeframes((samples * 32767).astype("<i2").tobytes())
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
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
                "-c:a",
                "pcm_s16le",
                str(decoded),
            ],
            check=True,
        )
        with wave.open(str(decoded), "rb") as stream:
            actual = (
                np.frombuffer(
                    stream.readframes(stream.getnframes()), dtype="<i2"
                ).astype(float)
                / 32768
            )
        results.append(
            compare_retained_signal(
                reference,
                actual[: len(reference)],
                rate,
                [
                    {
                        "observed": True,
                        "text": "synthetic-unit",
                        "start": 0.1,
                        "end": 0.9,
                    }
                ],
            )
        )
    assert results[0]["status"] == "pass"
    assert results[1]["status"] == "fail"
    source = tmp_path / "complete.wav"
    candidate = tmp_path / "complete.m4a"
    reference_entry = {
        "source": source,
        "selection": {"streamIndex": 0, "channels": [0]},
        "source_range": {
            "sourceId": "s1",
            "startTicks": 0,
            "endTicksExclusive": 1000,
            "timebase": {"num": 1, "den": 1000},
        },
        "fingerprint": source_fingerprint(source),
        "sync_ref": {"locator": "sync.json", "sha256": "a" * 64},
    }
    proof_request = {
        "proposal_ref": {"locator": "proposal.json", "sha256": "b" * 64},
        "proof_plan_ref": {"locator": "plan.json", "sha256": "c" * 64},
        "graph_hash": "d" * 64,
        "required_occurrences": ["occ-1"],
        "candidate_selection": {"streamIndex": 0, "channels": [0]},
        "windows": [
            {
                "occurrenceId": "occ-1",
                "localStartSeconds": 0,
                "localEndSeconds": 1,
                "expectedAudio": reference_entry,
                "retainedWordEdges": [
                    {"observed": True, "text": "unit", "start": 0.1, "end": 0.9}
                ],
                "fadeRanges": [],
            }
        ],
    }
    verifier = CuttingBoundaryVerifier(tmp_path / "qc")
    verified = verifier.verify(candidate, **proof_request)
    assert verified["status"] == "pass"
    assert verified["occurrenceCoverage"] == ["occ-1"]
    make_document("verification", verified)
    reference_entry["processing"] = {"noiseReduction": 0.4}
    assert verifier.verify(candidate, **proof_request)["status"] == "blocked"


def test_disconnected_short_residue_outside_words_is_detected():
    expected = np.zeros(16000)
    expected[1600:3200] = 0.1
    actual = expected.copy()
    actual[8000:8128] = 0.05
    result = compare_retained_signal(
        expected,
        actual,
        16000,
        [{"observed": True, "text": "unit", "start": 0.1, "end": 0.2}],
    )
    assert result["status"] == "fail"
    assert any(check["kind"] == "unexpected-signal" for check in result["checks"])


def test_unobserved_edges_or_fades_touching_speech_cannot_pass():
    signal = np.ones(1600) * 0.1
    assert compare_retained_signal(signal, signal, 16000, [])["status"] == "blocked"
    assert (
        compare_retained_signal(
            signal, signal, 16000, [{"text": "unit", "start": 0, "end": 0.1}]
        )["status"]
        == "blocked"
    )
    assert (
        compare_retained_signal(
            signal,
            signal,
            16000,
            [{"observed": True, "text": "unit", "start": 0, "end": 0.1}],
            fade_ranges=[{"start": 0, "end": 0.03}],
        )["status"]
        == "fail"
    )
