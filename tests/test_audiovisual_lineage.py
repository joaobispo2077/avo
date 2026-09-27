from __future__ import annotations

from copy import deepcopy

import pytest

from avo.timeline.contracts import file_fingerprint
from avo.timeline.lineage import (
    LineageError,
    lineage_from_materialization,
    validate_audiovisual_lineage,
)
from avo.timeline.picture_lineage import (
    build_audiovisual_lineage,
    build_picture_lineage,
)
from tests.test_picture_lineage import _revision, _tracks


def test_audiovisual_lineage_adds_audio_and_preserves_picture_view(tmp_path):
    source_a = tmp_path / "a.mov"
    source_b = tmp_path / "b.mov"
    overlay = tmp_path / "overlay.png"
    sfx = tmp_path / "sfx.wav"
    for path, data in (
        (source_a, b"a"),
        (source_b, b"b"),
        (overlay, b"overlay"),
        (sfx, b"sfx"),
    ):
        path.write_bytes(data)
    tracks = _tracks(overlay, tmp_path / "ignored.mp4")
    tracks["snapshot"]["audioTracks"] = {
        "layers": [
            {
                "layerId": "sfx",
                "role": "sfx",
                "source": file_fingerprint(sfx),
                "regions": [{"startTicks": 10, "endTicks": 20}],
            }
        ]
    }
    kwargs = {
        "cmap_revision": _revision(source_a, source_b),
        "tracks_revision": tracks,
        "canonical_input_lock": {"cmapRevisionHash": "c" * 64},
        "projection_hash": "p" * 64,
        "output": {"locator": str(tmp_path / "out.mp4"), "sha256": "o" * 64},
        "render_contract": {"transformations": []},
    }
    graph = build_audiovisual_lineage(**kwargs)
    picture = build_picture_lineage(**kwargs)
    assert validate_audiovisual_lineage(graph) == graph
    assert any(node.get("audioCarrying") for node in graph["nodes"])
    assert any(edge["operation"] == "mix" for edge in graph["edges"])
    materialization = {
        "audiovisualLineage": graph,
        "pictureLineage": picture,
    }
    assert lineage_from_materialization(materialization, audiovisual=False) == picture


def _graph() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "nodes": [
            {
                "nodeId": "source",
                "kind": "source",
                "role": "base",
                "mediaClass": "camera-original",
                "locator": "camera.mov",
                "sha256": "a" * 64,
                "pictureCarrying": True,
                "audioCarrying": True,
                "media": {},
            },
            {
                "nodeId": "output",
                "kind": "output",
                "role": "output",
                "mediaClass": "rendered-output",
                "locator": "candidate.mp4",
                "sha256": "b" * 64,
                "pictureCarrying": True,
                "audioCarrying": True,
                "media": {},
            },
        ],
        "edges": [
            {
                "edgeId": "edge-1",
                "from": "source",
                "to": "output",
                "operation": "encode",
                "order": 0,
                "parameters": {},
            }
        ],
        "rootIds": ["output"],
        "prohibitedAncestorClasses": [
            "proof",
            "preview",
            "proxy",
            "master",
            "delivery",
        ],
    }


@pytest.mark.parametrize("fault", ["missing", "cycle", "forbidden"])
def test_recursive_lineage_rejects_incomplete_cyclic_or_forbidden_graph(fault):
    graph = _graph()
    if fault == "missing":
        graph["edges"][0]["from"] = "absent"
    elif fault == "cycle":
        graph["edges"].append(
            {
                "edgeId": "edge-2",
                "from": "output",
                "to": "source",
                "operation": "render",
                "order": 1,
                "parameters": {},
            }
        )
    else:
        graph["nodes"][0]["mediaClass"] = "proof"
    with pytest.raises(LineageError):
        validate_audiovisual_lineage(graph)


def test_legacy_picture_lineage_remains_readable():
    legacy = {"nodes": [], "edges": [], "rootIds": [], "pictureLineageHash": "a" * 64}
    assert lineage_from_materialization({"pictureLineage": deepcopy(legacy)}) == legacy


def test_generated_audio_ancestry_is_expanded_recursively(tmp_path):
    source_a = tmp_path / "a.mov"
    source_b = tmp_path / "b.mov"
    overlay = tmp_path / "overlay.png"
    raw_audio = tmp_path / "raw.wav"
    inner = tmp_path / "inner.wav"
    outer = tmp_path / "outer.wav"
    for path, data in (
        (source_a, b"a"),
        (source_b, b"b"),
        (overlay, b"o"),
        (raw_audio, b"raw audio"),
        (inner, b"inner"),
        (outer, b"outer"),
    ):
        path.write_bytes(data)
    tracks = _tracks(overlay, tmp_path / "ignored.mp4")
    tracks["snapshot"]["audioTracks"] = {
        "layers": [
            {
                "layerId": "generated-sfx",
                "role": "sfx",
                "source": {
                    **file_fingerprint(outer),
                    "generatedAssetId": "outer-asset",
                },
            }
        ]
    }
    assets = {
        "outer-asset": {
            "assetId": "outer-asset",
            "inputs": [
                {
                    "artifactId": "inner-asset",
                    "ancestryRole": "generated",
                    "fingerprint": file_fingerprint(inner),
                }
            ],
        },
        "inner-asset": {
            "assetId": "inner-asset",
            "inputs": [
                {
                    "artifactId": "raw-audio",
                    "ancestryRole": "source",
                    "fingerprint": file_fingerprint(raw_audio),
                }
            ],
        },
    }
    graph = build_audiovisual_lineage(
        cmap_revision=_revision(source_a, source_b),
        tracks_revision=tracks,
        canonical_input_lock={"cmapRevisionHash": "c" * 64},
        projection_hash="p" * 64,
        output={"locator": str(tmp_path / "out.mp4"), "sha256": "o" * 64},
        render_contract={"transformations": []},
        generated_assets=assets,
    )
    validate_audiovisual_lineage(graph)
    ids = {node["nodeId"] for node in graph["nodes"]}
    assert {"generated-asset-inner-asset", "asset-input-inner-asset-0001"} <= ids
    links = {(edge["from"], edge["to"]) for edge in graph["edges"]}
    assert ("generated-asset-inner-asset", "audio-generated-sfx") in links
    assert ("asset-input-inner-asset-0001", "generated-asset-inner-asset") in links
