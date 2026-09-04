from __future__ import annotations

from copy import deepcopy

from avo.timeline.contracts import file_fingerprint
from avo.timeline.picture_lineage import build_picture_lineage


def _revision(source_a, source_b):
    return {
        "revisionId": "cmap-r0001",
        "contentHash": "c" * 64,
        "snapshot": {
            "sources": [
                {
                    "sourceId": "a",
                    "kind": "raw",
                    "locator": str(source_a),
                    "fingerprint": file_fingerprint(source_a),
                },
                {
                    "sourceId": "b",
                    "kind": "raw",
                    "locator": str(source_b),
                    "fingerprint": file_fingerprint(source_b),
                },
            ],
            "segments": [
                {
                    "segmentId": "s-b",
                    "sourceId": "b",
                    "in": {"ticks": 30},
                    "out": {"ticks": 40},
                },
                {
                    "segmentId": "s-a",
                    "sourceId": "a",
                    "in": {"ticks": 10},
                    "out": {"ticks": 20},
                },
            ],
        },
    }


def _tracks(overlay, ignored_base):
    return {
        "revisionId": "tracks-r0001",
        "contentHash": "t" * 64,
        "snapshot": {
            "videoTracks": {
                "layers": [
                    {
                        "layerId": "metadata-base",
                        "role": "base",
                        "source": {"locator": str(ignored_base)},
                        "regions": [],
                    },
                    {
                        "layerId": "logo",
                        "role": "overlay",
                        "source": file_fingerprint(overlay),
                        "regions": [{"startTicks": 0, "endTicks": 1000}],
                        "faceAvoidance": True,
                        "zOrder": 10,
                    },
                    {
                        "layerId": "title",
                        "role": "text",
                        "generator": {"id": "title-card", "version": "1"},
                        "source": {},
                        "regions": [{"startTicks": 0, "endTicks": 500}],
                        "faceAvoidance": True,
                        "zOrder": 20,
                    },
                ]
            }
        },
    }


def test_lineage_uses_declared_cmap_order_and_actual_compiled_layers(tmp_path):
    source_a = tmp_path / "a.mov"
    source_b = tmp_path / "b.mov"
    overlay = tmp_path / "logo.png"
    ignored = tmp_path / "ignored-proof.mp4"
    source_a.write_bytes(b"a")
    source_b.write_bytes(b"b")
    overlay.write_bytes(b"logo")
    lineage = build_picture_lineage(
        cmap_revision=_revision(source_a, source_b),
        tracks_revision=_tracks(overlay, ignored),
        canonical_input_lock={"cmapRevisionHash": "c" * 64},
        projection_hash="p" * 64,
        output={"locator": str(tmp_path / "out.mp4"), "sha256": "o" * 64},
        render_contract={"transformations": []},
    )
    segments = [
        node["sourceId"]
        for node in lineage["nodes"]
        if node.get("segmentId") in {"s-a", "s-b"}
    ]
    assert segments == ["b", "a"]
    assert [edge["parameters"]["segmentOrder"] for edge in lineage["edges"][:2]] == [
        0,
        1,
    ]
    locators = {node["locator"] for node in lineage["nodes"]}
    assert str(ignored) not in locators
    assert str(overlay) in locators
    assert any(node["kind"] == "generated" for node in lineage["nodes"])


def test_lineage_hash_is_stable_and_order_sensitive(tmp_path):
    a = tmp_path / "a.mov"
    b = tmp_path / "b.mov"
    overlay = tmp_path / "overlay.png"
    for path, data in ((a, b"a"), (b, b"b"), (overlay, b"o")):
        path.write_bytes(data)
    kwargs = {
        "cmap_revision": _revision(a, b),
        "tracks_revision": _tracks(overlay, tmp_path / "unused.mp4"),
        "canonical_input_lock": {"cmapRevisionHash": "c" * 64},
        "projection_hash": "p" * 64,
        "output": {"locator": str(tmp_path / "out.mp4"), "sha256": "o" * 64},
        "render_contract": {"transformations": []},
    }
    first = build_picture_lineage(**kwargs)
    second = build_picture_lineage(**deepcopy(kwargs))
    assert first["pictureLineageHash"] == second["pictureLineageHash"]
    reversed_cmap = deepcopy(kwargs["cmap_revision"])
    reversed_cmap["snapshot"]["segments"].reverse()
    changed = build_picture_lineage(**{**kwargs, "cmap_revision": reversed_cmap})
    assert changed["pictureLineageHash"] != first["pictureLineageHash"]


def test_lineage_records_declared_and_compiled_transform_edges(tmp_path):
    source_a = tmp_path / "a.mov"
    source_b = tmp_path / "b.mov"
    overlay = tmp_path / "overlay.png"
    for path, data in ((source_a, b"a"), (source_b, b"b"), (overlay, b"o")):
        path.write_bytes(data)
    tracks = _tracks(overlay, tmp_path / "ignored.mp4")
    overlay_layer = tracks["snapshot"]["videoTracks"]["layers"][1]
    overlay_layer["crop"] = {"left": 10, "top": 5, "width": 600, "height": 300}
    overlay_layer["provenance"] = {
        "mediaClass": "graphic",
        "approvalReference": "approval://overlay-crop-001",
    }
    lineage = build_picture_lineage(
        cmap_revision=_revision(source_a, source_b),
        tracks_revision=tracks,
        canonical_input_lock={"cmapRevisionHash": "c" * 64},
        projection_hash="p" * 64,
        output={"locator": str(tmp_path / "out.mp4"), "sha256": "o" * 64},
        render_contract={
            "transformations": [
                {
                    "operation": "reframe",
                    "parameters": {"aspect": "9:16"},
                    "approvalReference": "approval://reframe-001",
                }
            ]
        },
    )
    operations = [edge["operation"] for edge in lineage["edges"]]
    assert operations == [
        "trim",
        "trim",
        "reframe",
        "concat",
        "crop",
        "place/composite",
        "place/composite",
        "encode",
    ]
    approvals = {
        edge["operation"]: edge.get("approvalReference")
        for edge in lineage["edges"]
        if edge["operation"] in {"reframe", "crop"}
    }
    assert approvals == {
        "reframe": "approval://reframe-001",
        "crop": "approval://overlay-crop-001",
    }
