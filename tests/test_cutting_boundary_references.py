"""Verify retained-speech checks and the native reference recipe contract."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from numpy.testing import assert_allclose
from scipy.io import wavfile

from avo.adapters.qc import cutting_boundary as boundary
from avo.timeline.ports import ToolError


@pytest.fixture
def reference():
    return {
        "source": "original.wav",
        "selection": {"streamIndex": 1, "channels": [0]},
        "source_range": {
            "startTicks": 0,
            "endTicksExclusive": 100,
            "timebase": {"num": 1, "den": 100},
        },
        "fingerprint": {"sha256": "a" * 64},
        "sync_ref": {"id": "sync"},
        "processing": {
            "recipe": "native-dialogue-v1",
            "node": {
                "sourceSampleRate": 44100,
                "targetSampleRate": 48000,
                "sourceRange": {"startSample": 0, "endSampleExclusive": 44100},
                "outputRange": {"startSample": 0, "endSampleExclusive": 48000},
                "channelMap": [0, 0],
            },
            "dialogueNoiseReductionPolicy": None,
            "fadeSamples": [48, 96],
            "windowOffsetSamples": 240,
            "windowLengthSamples": 24000,
        },
    }


@pytest.mark.parametrize(
    "kind,expected_status",
    [
        ("same", "pass"),
        ("missing", "fail"),
        ("inverted", "fail"),
        ("silent", "blocked"),
        ("fade", "fail"),
        ("extra", "fail"),
    ],
)
def test_retained_signal_identifies_missing_changed_or_overlapped_speech(
    kind, expected_status
):
    expected = np.zeros(1000)
    expected[200:800] = np.sin(np.arange(600) / 3) * 0.5
    actual = expected.copy()
    fades = []
    if kind == "missing":
        actual[:] = 0
    elif kind == "inverted":
        actual *= -1
    elif kind == "silent":
        expected[:] = 0
        actual[:] = 0
    elif kind == "fade":
        fades = [{"start": 0.7, "end": 0.9}]
    elif kind == "extra":
        actual[:100] = 0.5
    result = boundary.compare_retained_signal(
        expected,
        actual,
        1000,
        [{"start": 0.2, "end": 0.8, "observed": True, "text": "word"}],
        fade_ranges=fades,
    )
    assert result["status"] == expected_status
    if kind == "same":
        assert [check["kind"] for check in result["checks"]] == [
            "unit",
            "onset",
            "tail",
        ]
        assert all(
            check["correlation"] == pytest.approx(1) for check in result["checks"]
        )
    if kind == "extra":
        assert any(check["kind"] == "unexpected-signal" for check in result["checks"])


@pytest.mark.parametrize(
    "edges",
    [
        [],
        [{"start": "bad", "end": 1}],
        [{"start": float("nan"), "end": 1}],
        [{"start": 0, "end": 2, "observed": True}],
        [{"start": 0, "end": 1}],
    ],
)
def test_unobserved_or_invalid_word_clock_blocks_claims(edges):
    result = boundary.compare_retained_signal(np.ones(100), np.ones(100), 100, edges)
    assert result["status"] == "blocked" and result["checks"] == []


@pytest.mark.parametrize("actual", [np.ones(99), np.full(100, float("nan"))])
def test_sample_coverage_and_nonfinite_signal_fail(actual):
    result = boundary.compare_retained_signal(
        np.ones(100), actual, 100, [{"start": 0, "end": 1, "status": "observed"}]
    )
    assert result["status"] == "fail" and "sample coverage" in result["reason"]


def test_native_reference_recipe_decodes_original_and_preserves_exact_window(
    reference, tmp_path, monkeypatch
):
    decode = Mock(return_value={"sampleRate": 44100})
    monkeypatch.setattr(boundary, "extract_dialogue_pcm", decode)
    monkeypatch.setattr(boundary, "_dialogue_noise_filter", lambda policy, node: "")
    commands = []

    def execute(cmd):
        commands.append(cmd)
        wavfile.write(cmd[-1], 48000, np.array([0, 2**30, -(2**30)], dtype=np.int32))

    monkeypatch.setattr(boundary, "_execute", execute)
    assert_allclose(boundary._native_reference(reference, tmp_path), [0, 0.5, -0.5])
    assert decode.call_args.args == ("original.wav",)
    assert decode.call_args.kwargs["native_render_seek"] is True
    cmd = commands[0]
    filt = cmd[cmd.index("-af") + 1]
    assert "atrim=end_sample=44100,asetpts=PTS-STARTPTS,aresample=48000" in filt
    assert "afade=t=in:ss=0:ns=48" in filt and "afade=t=out:ss=47904:ns=96" in filt
    assert "atrim=start_sample=240:end_sample=24240" in filt
    assert cmd[cmd.index("-map") + 1] == "0:1"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("recipe", "unsupported"),
        ("extra", "unsupported"),
        ("rate", "complete source"),
        ("span", "complete source"),
        ("gain", "gain differs"),
        ("channels", "routing differs"),
        ("bool-bound", "integer sample"),
        ("negative", "integer sample"),
        ("overrun", "exceed complete"),
        ("fade", "exceed complete"),
    ],
)
def test_native_reference_rejects_inexact_or_unrecognized_recipes(
    reference, change, reason
):
    entry = deepcopy(reference)
    recipe = entry["processing"]
    if change == "recipe":
        recipe["recipe"] = "unknown"
    elif change == "extra":
        recipe["untrusted"] = True
    elif change == "rate":
        recipe["node"]["targetSampleRate"] = 16000
    elif change == "span":
        entry["source_range"]["endTicksExclusive"] = 99
    elif change == "gain":
        entry["gainDb"] = 3
    elif change == "channels":
        entry["selection"]["channels"] = [1]
    elif change == "bool-bound":
        recipe["windowOffsetSamples"] = True
    elif change == "negative":
        recipe["fadeSamples"][0] = -1
    elif change == "overrun":
        recipe["windowLengthSamples"] = 48000
    elif change == "fade":
        recipe["fadeSamples"][0] = 48001
    with pytest.raises(ValueError, match=reason):
        boundary._native_recipe_basis(entry)


@pytest.mark.parametrize(
    "rate,pcm",
    [
        (16000, np.ones(4, dtype=np.int32)),
        (48000, np.ones(4, dtype=np.int16)),
        (48000, np.ones((4, 2), dtype=np.int32)),
        (48000, np.array([], dtype=np.int32)),
    ],
)
def test_native_reference_requires_mono_full_precision_pcm(tmp_path, rate, pcm):
    path = tmp_path / "reference.wav"
    wavfile.write(path, rate, pcm)
    with pytest.raises(ValueError, match="nonempty mono 48 kHz signed 32-bit PCM"):
        boundary._read_native_reference(path)


def test_legacy_reference_gain_and_fades_are_source_bound(
    reference, tmp_path, monkeypatch
):
    entry = {
        **reference,
        "gainDb": -6.020599913279624,
        "fadeInSeconds": 0.2,
        "fadeOutSeconds": 0.2,
    }
    entry.pop("processing")
    monkeypatch.setattr(
        boundary,
        "extract_dialogue_pcm",
        Mock(return_value={"analysisPath": str(tmp_path / "decoded.wav")}),
    )
    monkeypatch.setattr(boundary, "read_pcm", lambda path: (np.ones((10, 1)), 10))
    samples = boundary._reference_audio(entry, tmp_path)
    assert_allclose(samples, [0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0])
    with pytest.raises(ToolError, match="original audio selection is missing"):
        boundary._legacy_reference_audio([], tmp_path)
    for kwargs in [{"encoding": {}}, {"mix_reference": {}}]:
        with pytest.raises(ValueError, match="requires native"):
            boundary._reference_audio(entry, tmp_path, **kwargs)


@pytest.mark.parametrize("stereo", [False, True])
def test_encoded_reference_requires_declared_codec_and_channel_map(
    reference, tmp_path, monkeypatch, stereo
):
    execute = Mock()
    monkeypatch.setattr(boundary, "_execute", execute)
    encoding = {
        "codec": "aac",
        "sampleRate": 48000,
        "channelLayout": "dual-mono",
        "bitrate": boundary.PROOF_AUDIO_BITRATE,
    }
    path, filters = boundary._encoded_reference(
        tmp_path / "source.wav", np.ones(48), [reference], encoding, stereo=stereo
    )
    assert path == tmp_path / "source.m4a" and filters.startswith(
        "atrim=end_sample=48,"
    )
    assert ("-af" in execute.call_args.args[0]) != stereo
    with pytest.raises(ValueError, match="unsupported native reference encoding"):
        boundary._encoded_reference(
            Path("source"), [], [reference], {**encoding, "codec": "mp3"}
        )
