"""Lossy encoding belongs in the source reference, never in relaxed thresholds."""

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from avo.adapters.media.cutting_audio import read_pcm
from avo.adapters.media.cutting_preview import CuttingPreviewAdapter
from avo.adapters.media.proof_executor import PROOF_AUDIO_BITRATE
from avo.adapters.qc.cutting_boundary import (
    _native_reference,
    _reference_audio,
    compare_retained_signal,
)
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
def test_native_reference_preserves_low_pcm_bits_before_encoding(tmp_path, monkeypatch):
    source = tmp_path / "original.wav"
    values = (np.arange(48000, dtype=np.int64) * 7919 + 123456789).astype("int32")
    wavfile.write(source, 48000, values)

    # Isolate the reader from FFmpeg's choice of DSP sample precision.
    def write_processed(command):
        wavfile.write(Path(command[-1]), 48000, values)

    monkeypatch.setattr("avo.adapters.qc.cutting_boundary._execute", write_processed)
    reference = _native_reference(_entry(source, 48000), tmp_path / "ref")
    processed = next((tmp_path / "ref").glob("*-processed.wav"))
    rate, pcm = wavfile.read(processed)
    assert rate == 48000 and pcm.dtype == np.int32
    np.testing.assert_array_equal((reference * 2**31).astype("int32"), pcm)


@pytest.mark.integration
@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg and FFprobe required",
)
@pytest.mark.parametrize("sample_count", [800, 48800, 288800])
def test_encoded_reference_preserves_non_millisecond_sample_boundary(
    tmp_path, sample_count
):
    rate = 48000
    clock = np.arange(sample_count) / rate
    source = tmp_path / "original.wav"
    wavfile.write(
        source, rate, (np.sin(clock * 2 * np.pi * 440) * 2**28).astype("int32")
    )
    entry = _entry(source, rate)
    entry["source_range"]["endTicksExclusive"] = sample_count
    recipe = entry["processing"]
    recipe["windowLengthSamples"] = sample_count
    for bounds in ("sourceRange", "outputRange"):
        recipe["node"][bounds]["endSampleExclusive"] = sample_count
    reference = _reference_audio(entry, tmp_path / "ref", _encoding())
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-of",
                "json",
                str(tmp_path / "ref/package-native.m4a"),
            ]
        )
    )["streams"][0]
    assert probe["time_base"] == "1/48000"
    assert probe["duration_ts"] == sample_count
    assert len(reference) == (sample_count + 2) // 3


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


def _mixed_context(original, bed):
    from test_proof_audio_mix import graph, node

    nodes = [node("voice", "source", 0, 48000, [0, 0]), node("bed", "music", 0, 48000)]
    audio = graph(nodes, {"voice": original, "bed": bed})
    lock = {}
    for operation in audio["operations"]:
        if operation["kind"] != "trim":
            continue
        params = operation["parameters"]
        source = params["source"]
        digest = source_fingerprint(Path(source))["sha256"]
        params.update(
            sourceId=params["nodeId"],
            source={
                "locator": source,
                "sha256": digest,
                "mediaClass": "source",
                "streamIndex": 0,
            },
        )
        lock["source:" + params["nodeId"]] = digest
    return {
        "plan": {
            "audioGraph": audio,
            "canonicalInputLock": lock,
            "output": {"frameRate": {"num": 60, "den": 1}},
        },
        "window": {"startFrame": 0, "endFrameExclusive": 60},
    }


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
@pytest.mark.parametrize("missing", [None, "onset", "tail"])
def test_declared_stereo_bed_is_expected_but_missing_consonant_still_fails(
    tmp_path, missing
):
    rate = 48000
    clock = np.arange(rate) / rate
    signal = np.sin(clock * 2 * np.pi * 180) * 0.2
    noise = np.random.default_rng(4).normal(0, 0.003, rate)
    signal[:7680], signal[40320:] = noise[:7680], noise[40320:]
    signal[:2400] = 0
    original, candidate, bed = (
        tmp_path / n for n in ("voice.wav", "cut.wav", "bed.wav")
    )
    wavfile.write(
        original, rate, (np.column_stack((signal, signal)) * 2**31).astype("int32")
    )
    # Stereo asymmetry matters to AAC's stereo allocation even when checking left.
    music = np.column_stack(
        (
            np.sin(clock * 2 * np.pi * 630) * 0.0006,
            np.sin(clock * 2 * np.pi * 870) * 0.008,
        )
    )
    music[:2400, 0] *= 20
    wavfile.write(bed, rate, (music * 2**31).astype("int32"))
    context = _mixed_context(original, bed)
    expected = _reference_audio(
        _entry(original, rate), tmp_path / "ref", _encoding(), context
    )
    changed = signal.copy()
    if missing == "onset":
        changed[4320:6720] = 0
    elif missing == "tail":
        changed[41280:43680] = 0
    wavfile.write(
        candidate, rate, (np.column_stack((changed, changed)) * 2**31).astype("int32")
    )
    actual = _reference_audio(
        _entry(candidate, rate), tmp_path / "actual", _encoding(), context
    )
    edges = [{"text": "synthetic", "start": 0.1, "end": 0.9, "observed": True}]
    result = compare_retained_signal(expected, actual, 16000, edges)
    assert result["status"] == ("pass" if missing is None else "fail")
    if missing:
        assert any(
            c["kind"] == missing and c["status"] == "fail" for c in result["checks"]
        )
    else:
        voice_only = _reference_audio(
            _entry(original, rate), tmp_path / "voice-only", _encoding()
        )
        assert (
            compare_retained_signal(voice_only, actual, 16000, edges)["status"]
            == "fail"
        )
    bed.write_bytes(b"changed source")
    with pytest.raises(RuntimeError, match="source bytes changed"):
        _reference_audio(
            _entry(original, rate), tmp_path / "stale", _encoding(), context
        )


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_two_mixed_windows_do_not_rewrite_fingerprinted_scratch(tmp_path):
    from avo.adapters.qc.cutting_boundary import CuttingBoundaryVerifier
    from avo.timeline.contracts import fingerprint_stage

    rate = 48000
    clock = np.arange(rate) / rate
    voice = np.sin(clock * 2 * np.pi * 180) * 0.2
    bed_signal = np.sin(clock * 2 * np.pi * 730) * 0.01
    original, bed = tmp_path / "voice.wav", tmp_path / "bed.wav"
    for path, signal in ((original, voice), (bed, bed_signal)):
        wavfile.write(
            path, rate, (np.column_stack((signal, signal)) * 2**31).astype("int32")
        )
    contexts, entries, candidates = [], [], []
    for number, offset in enumerate((0, 4800)):
        context = _mixed_context(original, bed)
        context["window"]["startFrame"] = offset // 800
        entry = _entry(original, rate)
        entry["processing"].update(
            windowOffsetSamples=offset, windowLengthSamples=rate - offset
        )
        folder = tmp_path / ("candidate-" + str(number))
        _reference_audio(entry, folder, _encoding(), context)
        candidates.append(folder / "package-mixed.m4a")
        contexts.append(context)
        entries.append(entry)
    verifier = CuttingBoundaryVerifier(tmp_path / "verification")
    with fingerprint_stage(verify_on_exit=True):
        for candidate, entry, context in zip(candidates, entries, contexts):
            duration = entry["processing"]["windowLengthSamples"] / rate
            result = verifier.verify(
                candidate,
                proposal_ref={"locator": "proposal.json", "sha256": "a" * 64},
                proof_plan_ref={"path": "plan.json", "sha256": "b" * 64},
                graph_hash="c" * 64,
                required_occurrences=["one"],
                reference_encoding=_encoding(),
                mix_reference=context,
                candidate_selection={"streamIndex": 0, "channels": [0]},
                windows=[
                    {
                        "occurrenceId": "one",
                        "localStartSeconds": 0,
                        "localEndSeconds": duration,
                        "expectedAudio": [entry],
                        "retainedWordEdges": [
                            {
                                "text": "synthetic",
                                "start": 0.1,
                                "end": duration - 0.1,
                                "observed": True,
                            }
                        ],
                        "fadeRanges": [],
                    }
                ],
            )
            assert result["status"] == "pass", result
