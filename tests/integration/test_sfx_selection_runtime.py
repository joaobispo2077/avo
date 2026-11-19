"""Selected source-native sound markers survive encoding and absolute cut windows."""

import shutil
import wave
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest
from tests.integration.test_ffmpeg_proof_executor import _execution, _pcm
from tests.integration.test_proof_audio_mix_executor import _with_music
from tests.test_sfx_catalog import annotate, scan
from tests.test_sound_choices import inputs

from avo.adapters.media.proof_executor import execute_ffmpeg_proof
from avo.adapters.media.sfx_analysis import SfxAnalyzer
from avo.sfx_catalog import SfxCatalogService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.sound_compilation import append_selected_sound
from avo.timeline.sound_planning import freeze_sound_choices

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
        reason="actual ffmpeg/ffprobe required",
    ),
]


def selected_sound(tmp_path, rate):
    library = tmp_path / "library"
    library.mkdir()
    signal = np.zeros(rate, dtype=np.float64)
    marker = rate * 3 // 20
    signal[marker] = 0.5
    tail = np.arange(rate // 5)
    signal[marker + 1 : marker + 1 + len(tail)] = (
        0.12 * np.exp(-tail / (rate / 25)) * np.sin(2 * np.pi * 250 * tail / rate)
    )
    path = library / "impact.wav"
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes((signal * 32767).astype("<i2").tobytes())
    catalogue = SfxCatalogService(
        SimpleNamespace(raw_dir=tmp_path / "metadata"),
        roots={"test": library},
        analyzer=SfxAnalyzer(),
    )
    generation = scan(catalogue)
    entry = generation["entries"][0]
    generation = annotate(
        catalogue,
        generation["generationId"],
        entry["entryId"],
        {
            "rights": {
                "status": "licensed",
                "license": "generated-test-fixture",
                "evidenceRef": "synthetic-fixture",
            },
            "marker": {"sample": marker, "reviewerRef": "known-synthetic-impact"},
        },
    )
    entry = generation["entries"][0]
    # Source-native, deliberately non-aligned trim at 44.1 kHz.
    fixture = tmp_path / "choice-fixture"
    fixture.mkdir()
    _, event, choice, context, clock = inputs(fixture)
    event.update(
        programFrame=30, visibleRange={"startFrame": 24, "endFrameExclusive": 48}
    )
    choice.update(
        entryId=entry["entryId"],
        trimRange={"startSample": rate // 20 - 1, "endSampleExclusive": rate * 3 // 4},
    )
    choice["mix"].update(
        sourceLayout="mono", targetLayout="stereo", channelMap=[0, 0], gainDb=-12
    )
    clock.update(frameRate={"num": 30000, "den": 1001}, programEndFrame=60)
    choices = freeze_sound_choices(
        [event], [choice], entries=[entry], contexts=[context], clock=clock
    )["choices"]
    assert choices[0]["fit"]["status"] == "fit", choices
    source = {
        "locator": str(path),
        "sha256": file_fingerprint(path)["sha256"],
        "mediaClass": "source",
        "streamIndex": 0,
    }
    return choices, {event["eventId"]: source}


@pytest.mark.parametrize("rate", [44100, 48000, 96000])
def test_encoded_selected_marker_tail_channels_and_windows_keep_single_playback(
    tmp_path, rate
):
    execution = _execution(tmp_path)
    execution["output"].update(
        conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le"
    )
    baseline = tmp_path / "baseline.mkv"
    execute_ffmpeg_proof(execution, baseline)
    choices, sources = selected_sound(tmp_path, rate)
    original = deepcopy(execution)
    mixed = append_selected_sound(execution, choices, source_refs=sources)
    assert execution == original
    assert append_selected_sound(mixed, choices, source_refs=sources) == mixed
    output = tmp_path / "selected.mkv"
    execute_ffmpeg_proof(mixed, output)
    clean, result = _pcm(baseline), _pcm(output)
    assert len(result) == len(clean) == 96096
    delta = result - clean
    fit = choices[0]["fit"]
    first, last = (
        fit["event"]["scheduledAudioStartSample"],
        fit["scheduledAudioEndSample"],
    )
    np.testing.assert_allclose(delta[:first], 0, atol=3e-7)
    np.testing.assert_allclose(delta[last:], 0, atol=3e-7)
    np.testing.assert_allclose(delta[:, 0], delta[:, 1], atol=3e-7)
    observed = int(np.argmax(np.abs(delta[:, 0])))
    assert abs(observed - fit["event"]["resolvedImpactSample"]) <= 1602
    assert np.max(np.abs(delta[observed + 100 : observed + 3000])) > 0.001
    assert (
        np.max(np.abs(delta)) < 0.14
    )  # A doubled 0.5-amplitude fixture at -12 dB fails.
    mixed["window"] = {"startFrame": 25, "endFrameExclusive": 45}
    window = tmp_path / "window.mkv"
    execute_ffmpeg_proof(mixed, window)
    np.testing.assert_allclose(_pcm(window), result[40040:72072], atol=3e-7)
    if rate == 48000:
        music = _with_music(execution)
        music_base, music_effect = (
            tmp_path / "music-base.mkv",
            tmp_path / "music-sound.mkv",
        )
        execute_ffmpeg_proof(music, music_base)
        execute_ffmpeg_proof(
            append_selected_sound(music, choices, source_refs=sources), music_effect
        )
        np.testing.assert_allclose(
            _pcm(music_effect) - _pcm(music_base), delta, atol=3e-7
        )


def test_selected_ducking_uses_existing_dialogue_without_replacing_its_audio(tmp_path):
    execution = _execution(tmp_path)
    execution["output"].update(
        conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le"
    )
    choices, sources = selected_sound(tmp_path, 48000)
    prior = choices[0]
    event = {**prior["fit"]["opportunity"], "programFrame": 35}
    choice = {
        "eventId": event["eventId"],
        "entryId": prior["sourceEntry"]["entryId"],
        "trimRange": prior["fit"]["trimRange"],
        "mix": deepcopy(prior["mix"]),
    }
    context = {
        "cueId": event["cueId"],
        "role": "authored-graphic",
        "orderedEventIds": [],
        "syntheticEffectApproved": False,
    }

    def select():
        return freeze_sound_choices(
            [event],
            [choice],
            entries=[prior["sourceEntry"]],
            contexts=[context],
            clock=prior["fit"]["clock"],
        )["choices"]

    ordinary = append_selected_sound(execution, select(), source_refs=sources)
    choice["mix"]["ducking"] = {
        "sidechainLayerId": "dialogue",
        "amountDb": 8,
        "attackMs": 20,
        "releaseMs": 250,
    }
    ducked = append_selected_sound(
        execution,
        select(),
        source_refs=sources,
        sidechain_nodes={"dialogue": ["audio-0", "audio-1"]},
    )
    paths = [
        tmp_path / name for name in ("baseline-duck.mkv", "ordinary.mkv", "ducked.mkv")
    ]
    for value, path in zip((execution, ordinary, ducked), paths, strict=True):
        execute_ffmpeg_proof(value, path)
    base, plain, quiet = [_pcm(path) for path in paths]
    unprocessed, controlled = plain - base, quiet - base
    assert np.sqrt(np.mean(controlled**2)) < np.sqrt(np.mean(unprocessed**2)) * 0.9
    np.testing.assert_allclose(quiet[:48000], base[:48000], atol=3e-7)
    np.testing.assert_allclose(quiet[90000:], base[90000:], atol=3e-7)
    assert ducked["audioGraph"]["nodes"][:2] == execution["audioGraph"]["nodes"]
