import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from avo.adapters.media.proof_audio_mix import (
    render_proof_audio_mix,
    validate_proof_audio_mix,
)


def pcm(path, values):
    values = np.asarray(values, dtype="<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(values.shape[1])
        f.setsampwidth(2)
        f.setframerate(48000)
        f.writeframes(values.tobytes())
    return path


def node(name, kind, first, last, channel_map=None):
    return {
        "nodeId": name,
        "kind": kind,
        "sourceSampleRate": 48000,
        "targetSampleRate": 48000,
        "sourceRange": region(0, last - first),
        "outputRange": region(first, last),
        "sourceLayout": "stereo",
        "targetLayout": "stereo",
        "channelMap": channel_map or [0, 1],
        "latencyCompensationSamples": 0,
    }


def region(first, last):
    return {"startSample": first, "endSampleExclusive": last}


def graph(nodes, paths, extra=()):
    end = max(n["outputRange"]["endSampleExclusive"] for n in nodes)
    return {
        "sampleRate": 48000,
        "singleFinalEncode": True,
        "nodes": nodes,
        "operations": [
            {
                "operationId": "trim-" + n["nodeId"],
                "kind": "trim",
                "range": n["outputRange"],
                "parameters": {
                    "nodeId": n["nodeId"],
                    "source": str(paths[n["nodeId"]]),
                },
            }
            for n in nodes
            if n["kind"] != "silence"
        ]
        + [
            {
                "operationId": "mix-final",
                "kind": "mix",
                "range": region(0, end),
                "parameters": {},
            },
            *extra,
            {
                "operationId": "encode-final",
                "kind": "encode",
                "range": region(0, end),
                "parameters": {},
            },
        ],
    }


def resolve(n, p):
    return Path(p["source"]), 0


def test_native_endpoint_resampling_trims_only_verified_surplus(tmp_path):
    from avo.adapters.media.proof_audio_mix import _stage_source

    source = tmp_path / "native-96k.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(96000)
        output.writeframes(np.zeros((384000, 2), dtype="<i2").tobytes())
    item = node("riser", "sfx", 0, 184311)
    item.update(sourceSampleRate=96000, sourceRange=region(15377, 384000))
    target = tmp_path / "resampled.wav"
    _stage_source(item, (source, 0), target)
    probe = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=duration_ts",
            "-of",
            "csv=p=0",
            str(target),
        ],
        text=True,
    )
    assert int(probe.strip()) == 184311
    item["sourceRange"]["endSampleExclusive"] += 1
    with pytest.raises(ValueError, match="decoded EOF"):
        _stage_source(item, (source, 0), tmp_path / "missing-source-sample.wav")


def read(path):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "s32le",
            "-acodec",
            "pcm_s32le",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype="<i4").reshape(-1, 2) / 2**31


def test_mix_places_trims_maps_and_excludes_music_outside_region(tmp_path):
    voice = pcm(tmp_path / "voice.wav", np.full((4800, 2), 1000))
    music = pcm(tmp_path / "music.wav", np.tile([2000, 4000], (4800, 1)))
    nodes = [
        node("voice", "source", 0, 4800),
        node("music", "music", 1200, 2400, [1, 1]),
    ]
    g = graph(nodes, {"voice": voice, "music": music})
    g["nodes"][1]["sourceRange"] = region(300, 1500)
    result = render_proof_audio_mix(g, tmp_path / "mix.wav", source_resolver=resolve)
    data = read(tmp_path / "mix.wav")
    assert data.shape == (4800, 2)
    np.testing.assert_allclose(data[:1200], 1000 / 32768, atol=1e-6)
    np.testing.assert_allclose(data[1200:2400], 5000 / 32768, atol=1e-6)
    np.testing.assert_allclose(data[2400:], 1000 / 32768, atol=1e-6)
    assert result["audioEncodeCount"] == 0


def test_gain_fades_and_window_keep_exact_sample_count(tmp_path):
    voice = pcm(tmp_path / "voice.wav", np.full((4800, 2), 3000))
    n = node("voice", "source", 0, 4800)
    operations = [
        {
            "operationId": "gain-voice",
            "kind": "gain",
            "range": region(0, 4800),
            "parameters": {"nodeId": "voice", "gainDb": -6},
        },
        {
            "operationId": "fade-voice",
            "kind": "fade",
            "range": region(0, 4800),
            "parameters": {
                "nodeId": "voice",
                "fadeInSamples": 1200,
                "fadeOutSamples": 1200,
            },
        },
    ]
    g = graph([n], {"voice": voice}, operations)
    render_proof_audio_mix(
        g, tmp_path / "mix.wav", source_resolver=resolve, window=(600, 4200)
    )
    data = read(tmp_path / "mix.wav")
    assert len(data) == 3600
    assert data[0, 0] < data[1800, 0] * 0.55
    assert data[-1, 0] < data[1800, 0] * 0.55
    assert data[1800, 0] == pytest.approx(3000 / 32768 * 10 ** (-6 / 20), abs=1e-5)


def test_rejects_unknown_ancestry_before_output(tmp_path):
    n = node("voice", "source", 0, 4800)
    g = graph([n], {"voice": tmp_path / "unknown.wav"})

    def deny(n, p):
        raise ValueError("unregistered source ancestry")

    with pytest.raises(ValueError, match="ancestry"):
        render_proof_audio_mix(g, tmp_path / "mix.wav", source_resolver=deny)
    assert not (tmp_path / "mix.wav").exists()


def test_unexplained_gap_fails(tmp_path):
    n = node("voice", "source", 1200, 2400)
    g = graph([n], {"voice": tmp_path / "voice.wav"})
    with pytest.raises(ValueError, match="gap"):
        render_proof_audio_mix(g, tmp_path / "mix.wav", source_resolver=resolve)


def test_ephemeral_lead_still_requires_original_source_validation(tmp_path):
    voice = pcm(tmp_path / "voice.wav", np.full((4800, 2), 1000))
    lead = pcm(tmp_path / "lead.wav", np.full((4800, 2), 2000))
    g = graph([node("voice", "source", 0, 4800)], {"voice": voice})
    seen = []

    def resolver(n, p):
        seen.append(n["nodeId"])
        return resolve(n, p)

    render_proof_audio_mix(
        g,
        tmp_path / "mix.wav",
        source_resolver=resolver,
        lead_pcm=lead,
        lead_node_ids={"voice"},
    )
    assert seen == ["voice"]
    np.testing.assert_allclose(read(tmp_path / "mix.wav"), 2000 / 32768, atol=1e-6)


def test_ducking_reduces_music_under_ephemeral_dialogue(tmp_path):
    voice = pcm(tmp_path / "voice.wav", np.full((4800, 2), 10000))
    music = pcm(tmp_path / "music.wav", np.full((4800, 2), 2000))
    nodes = [node("voice", "source", 0, 4800), node("music", "music", 0, 4800)]
    duck = {
        "operationId": "duck-music",
        "kind": "duck",
        "range": region(0, 4800),
        "parameters": {
            "nodeId": "music",
            "sidechainNodeIds": ["voice"],
            "amountDb": 8,
            "attackMs": 1,
            "releaseMs": 50,
        },
    }
    g = graph(nodes, {"voice": voice, "music": music}, [duck])
    render_proof_audio_mix(
        g,
        tmp_path / "mix.wav",
        source_resolver=resolve,
        lead_pcm=voice,
        lead_node_ids={"voice"},
    )
    data = read(tmp_path / "mix.wav")
    assert 10000 / 32768 < data[4000, 0] < 11000 / 32768


def test_windowed_ephemeral_lead_keeps_absolute_origin(tmp_path):
    voice = pcm(tmp_path / "voice.wav", np.full((4800, 2), 1000))
    lead = pcm(tmp_path / "lead.wav", np.full((1200, 2), 2000))
    g = graph([node("voice", "source", 0, 4800)], {"voice": voice})
    render_proof_audio_mix(
        g,
        tmp_path / "mix.wav",
        source_resolver=resolve,
        lead_pcm=lead,
        lead_node_ids={"voice"},
        window=(2400, 3600),
        lead_pcm_start_sample=2400,
    )
    np.testing.assert_allclose(read(tmp_path / "mix.wav"), 2000 / 32768, atol=1e-6)


def test_preflight_rejects_unknown_filter_and_invalid_channel(tmp_path):
    n = node("voice", "source", 0, 4800, [0, 2])
    g = graph([n], {"voice": tmp_path / "voice.wav"})
    with pytest.raises(ValueError, match="missing source channel"):
        validate_proof_audio_mix(g, source_resolver=resolve)

    n["channelMap"] = [0, 1]
    g = graph(
        [n],
        {"voice": tmp_path / "voice.wav"},
        [
            {
                "operationId": "filter-unknown",
                "kind": "filter",
                "range": region(0, 4800),
                "parameters": {"nodeId": "voice", "filter": "arbitrary"},
            }
        ],
    )
    with pytest.raises(ValueError, match="Unsupported mix operation"):
        validate_proof_audio_mix(g, source_resolver=resolve)


def test_float_mix_retains_headroom_and_reports_measured_peak(tmp_path):
    voice = pcm(tmp_path / "voice.wav", np.full((4800, 2), 26000))
    music = pcm(tmp_path / "music.wav", np.full((4800, 2), 26000))
    nodes = [node("voice", "source", 0, 4800), node("music", "music", 0, 4800)]
    g = graph(nodes, {"voice": voice, "music": music})
    result = render_proof_audio_mix(g, tmp_path / "mix.wav", source_resolver=resolve)
    assert result["pcmCodec"] == "pcm_f32le"
    assert result["measurement"]["peakDbfs"] == pytest.approx(
        20 * np.log10(52000 / 32768), abs=1e-4
    )
    assert result["measurement"]["rmsDbfs"] == pytest.approx(
        result["measurement"]["peakDbfs"], abs=1e-4
    )


def test_source_eof_is_rejected_before_silence_padding(tmp_path):
    short = pcm(tmp_path / "short.wav", np.full((1200, 2), 1000))
    g = graph([node("voice", "source", 0, 4800)], {"voice": short})
    with pytest.raises(ValueError, match="decoded EOF"):
        render_proof_audio_mix(g, tmp_path / "mix.wav", source_resolver=resolve)
    assert not (tmp_path / "mix.wav").exists()


def test_short_ephemeral_dialogue_cannot_be_padded_as_valid(tmp_path):
    original = pcm(tmp_path / "original.wav", np.full((4800, 2), 1000))
    lead = pcm(tmp_path / "short.wav", np.full((1200, 2), 1000))
    g = graph([node("voice", "source", 0, 4800)], {"voice": original})
    with pytest.raises(ValueError, match="exact requested window"):
        render_proof_audio_mix(
            g,
            tmp_path / "mix.wav",
            source_resolver=resolve,
            lead_pcm=lead,
            lead_node_ids={"voice"},
        )
    assert not (tmp_path / "mix.wav").exists()


def test_finite_ducked_beds_preserve_tails_and_do_not_repeat(tmp_path):
    dialogue = np.zeros((96000, 2))
    dialogue[:4800] = 10000
    voice = pcm(tmp_path / "quiet-lead.wav", dialogue)
    first = pcm(tmp_path / "first-bed.wav", np.full((32000, 2), 2000))
    second = pcm(tmp_path / "second-bed.wav", np.full((32000, 2), 4000))
    nodes = [
        node("voice", "source", 0, 96000),
        node("first", "music", 0, 32000),
        node("second", "music", 48000, 80000),
    ]
    ducks = [
        {
            "operationId": "duck-" + item["nodeId"],
            "kind": "duck",
            "range": item["outputRange"],
            "parameters": {
                "nodeId": item["nodeId"],
                "sidechainNodeIds": ["voice"],
                "amountDb": 2,
            },
        }
        for item in nodes[1:]
    ]
    source_graph = graph(
        nodes, {"voice": voice, "first": first, "second": second}, ducks
    )
    expected = np.zeros((96000, 2))
    expected[:32000] = 2000 / 32768
    expected[48000:80000] = 4000 / 32768
    reference = None
    for attempt in range(8):
        destination = tmp_path / f"mix-{attempt}.wav"
        render_proof_audio_mix(
            source_graph,
            destination,
            source_resolver=resolve,
            lead_pcm=voice,
            lead_node_ids={"voice"},
        )
        observed = read(destination)
        np.testing.assert_allclose(observed[30000:], expected[30000:], atol=1e-6)
        if reference is not None:
            np.testing.assert_array_equal(observed, reference)
        reference = observed
