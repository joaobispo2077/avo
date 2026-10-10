from __future__ import annotations

import pytest

from avo.adapters.media.audio_tracks import AudioGraphError, compile_audio_layers


def layer(layer_id, role, order, start, end, **extra):
    return {
        "layerId": layer_id,
        "role": role,
        "order": order,
        "source": {"locator": f"{layer_id}.wav", "sha256": "a" * 64, "sizeBytes": 1},
        "regions": [
            {
                "regionId": f"r-{layer_id}",
                "startTicks": start,
                "endTicks": end,
                "cueIds": [f"cue-{layer_id}"],
                **extra.pop("region", {}),
            }
        ],
        **extra,
    }


def test_compiles_dialogue_three_music_beds_sfx_ambience_and_ducking():
    layers = [
        layer("dialogue", "dialogue", 0, 0, 10000, channels=[0, 1], gainDb=0),
        layer(
            "music-a",
            "music",
            1,
            0,
            3000,
            gainDb=-24,
            ducking={"amountDb": 8, "attackMs": 20, "releaseMs": 250},
            fades={"inTicks": 250, "outTicks": 300},
        ),
        layer("music-b", "music", 2, 3000, 6000, gainDb=-22, ducking={"amountDb": 8}),
        layer("music-c", "music", 3, 6000, 10000, gainDb=-23, ducking={"amountDb": 8}),
        layer("sfx", "sfx", 4, 1500, 1800, gainDb=-12),
        layer("room", "ambience", 5, 0, 10000, gainDb=-30),
    ]
    compiled = compile_audio_layers(layers, first_input_index=1)
    graph = ";".join(compiled["filters"])
    assert "sidechaincompress" in graph
    assert "afade=t=in" in graph and "afade=t=out" in graph
    assert graph.count("adelay=") == 5
    assert compiled["outputLabel"] == "[outa]"
    assert {item["role"] for item in compiled["trace"]} == {
        "dialogue",
        "music",
        "sfx",
        "ambience",
    }
    assert len([item for item in compiled["trace"] if item["role"] == "music"]) == 3


def test_muted_layer_is_traced_but_not_compiled():
    compiled = compile_audio_layers(
        [layer("muted", "music", 1, 0, 1000, mute=True)], first_input_index=1
    )
    assert compiled["inputs"] == []
    assert compiled["trace"][0]["enabled"] is False


def test_ducking_padding_is_bounded_at_absolute_sample_end():
    compiled = compile_audio_layers(
        [
            layer("dialogue", "dialogue", 0, 0, 10000),
            layer("bed", "music", 1, 3000, 6500, ducking={"amountDb": 8}),
        ]
    )
    graph = ";".join(compiled["filters"])
    assert "[abed]apad[abedpad]" in graph
    assert "[dlgsc0]apad[dlgsc0pad]" in graph
    assert "atrim=end_sample=312000[abedd]" in graph
    assert "[dlgmix][abedd]amix" in graph


def test_ducking_without_a_bounded_region_fails_closed():
    with pytest.raises(AudioGraphError, match="positive region end"):
        compile_audio_layers(
            [
                layer("dialogue", "dialogue", 0, 0, 10000),
                layer("bed", "music", 1, 0, 0, ducking={"amountDb": 8}),
            ]
        )
