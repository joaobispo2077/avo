from __future__ import annotations

import pytest

from avo.adapters.media.video_tracks import VideoTrackError, compile_video_layers


def layer(layer_id, role, order, z, **extra):
    return {
        "layerId": layer_id,
        "role": role,
        "order": order,
        "zOrder": z,
        "source": {"locator": f"{layer_id}.png", "sha256": "a" * 64, "sizeBytes": 1},
        "regions": [{"regionId": f"r-{layer_id}", "startTicks": 100, "endTicks": 500, "cueIds": [f"cue-{layer_id}"]}],
        "fit": "contain",
        "faceAvoidance": role == "base" or True,
        "safeZones": ["face", "captions"],
        **extra,
    }


def test_compiles_all_visual_roles_z_order_and_captions_last():
    layers = [
        layer("base", "base", 0, 0),
        layer("clip", "clip", 1, 10),
        layer("image", "image", 2, 20),
        layer("text", "text", 3, 30),
        layer("card", "card", 4, 40),
        layer("graphic", "graphic", 5, 50),
        layer("captions", "caption", 6, 100),
    ]
    compiled = compile_video_layers(layers)
    assert [item["layerId"] for item in compiled["overlays"]] == ["clip", "image", "text", "card", "graphic"]
    assert compiled["captions"]["layerId"] == "captions"
    assert compiled["trace"][-1]["role"] == "caption"


def test_unsupported_composite_and_missing_avoidance_block():
    bad = layer("overlay", "graphic", 1, 1, composite={"mode": "unsupported"})
    with pytest.raises(VideoTrackError):
        compile_video_layers([bad])
    no_face = layer("overlay", "graphic", 1, 1)
    no_face["faceAvoidance"] = False
    with pytest.raises(VideoTrackError):
        compile_video_layers([no_face])
