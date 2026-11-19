"""Measure the exact sidechain and post-duck effect in the native PCM mix."""

from copy import deepcopy

import numpy as np
import pytest
from tests.test_proof_audio_mix import graph, node, pcm, read, region, resolve

from avo.adapters.media.proof_audio_mix import render_proof_audio_mix

pytestmark = pytest.mark.integration


def test_opt_in_dialogue_margin_preserves_mix_and_reports_actual_overlap(tmp_path):
    samples = np.arange(4800)
    tone = np.column_stack([np.sin(2 * np.pi * 1000 * samples / 48000)] * 2)
    voice = pcm(tmp_path / "voice.wav", 9000 * tone)
    effect = pcm(tmp_path / "sfx.wav", 7000 * tone[:2400])
    duck = {
        "operationId": "duck-effect",
        "kind": "duck",
        "range": region(1200, 3600),
        "parameters": {
            "nodeId": "effect",
            "sidechainNodeIds": ["voice"],
            "attackMs": 20,
            "releaseMs": 40,
            "amountDb": 8,
        },
    }
    program = graph(
        [node("voice", "source", 0, 4800), node("effect", "sfx", 1200, 3600)],
        {"voice": voice, "effect": effect},
        [duck],
    )
    window = (1800, 4200)
    original, measured = tmp_path / "original.wav", tmp_path / "measured.wav"
    baseline = render_proof_audio_mix(
        program, original, source_resolver=resolve, window=window
    )
    selected = deepcopy(program)
    selected["operations"][-2]["parameters"]["minimumDialogueMarginDb"] = 36
    result = render_proof_audio_mix(
        selected, measured, source_resolver=resolve, window=window
    )
    np.testing.assert_array_equal(read(measured), read(original))
    assert result["measurement"] == baseline["measurement"]
    assert "dialogueBalance" not in baseline
    (review,) = result["dialogueBalance"]
    assert review["nodeId"] == "effect"
    assert review["window"] == region(1800, 3600)
    assert review["bandHz"] == [300, 4000]
    assert review["status"] == "measured"
    assert review["dialogueRmsDbfs"] > review["effectRmsDbfs"]
