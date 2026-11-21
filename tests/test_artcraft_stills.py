"""Closed still roles, placement, and editable-source dependencies."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.timeline import artcraft_stills
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.tracks import TrackError, resolve_tracks


@pytest.fixture
def card_proof(tmp_path, monkeypatch):
    path = tmp_path / "job.json"
    path.write_text("retained card job fixture", encoding="utf-8")
    reference = {"job": file_fingerprint(path), "exportHead": "a" * 64}
    source = {
        "locator": str(tmp_path / "card.png"),
        "sha256": "b" * 64,
        "sizeBytes": 32,
    }
    job = {
        "request": {
            "provider": "neutral-channel",
            "context": {"kind": "provider-only"},
        },
        "workspace": str(tmp_path),
        "output": {"role": "generated-still", "format": "png"},
        "observation": {"app": "vectorcraft"},
        "inputs": [],
    }
    event = {
        "outputs": [source],
        "stillEvidence": {"width": 320, "height": 180},
    }
    monkeypatch.setattr(
        artcraft_stills, "read_authoring_export", lambda *_, **__: (job, event)
    )
    layer = {
        "layerId": "vector-card",
        "role": "overlay",
        "generatedStillRef": reference,
        "source": source,
        "placement": {"x": 160, "y": 90, "width": 320, "height": 180},
        "zOrder": 3,
        "regions": [{"startTicks": 1, "endTicks": 12}],
    }
    store = SimpleNamespace(
        revision=lambda _: {"snapshot": {"videoTracks": {"layers": [layer]}}}
    )
    workspace = SimpleNamespace(
        store=lambda _: store,
        require_active=lambda _: {"headRevisionId": "tracks-one"},
        project={"provider": "neutral-channel"},
        raw_dir=tmp_path,
        project_path=tmp_path / "avo.project.json",
        video_id="current-video",
    )
    operation = {
        "kind": "overlay-image",
        "operationId": "vector-card",
        "inputs": ["program-picture", "generated-still:vector-card"],
        "outputRange": {"startFrame": 1, "endFrameExclusive": 12},
        "parameters": {
            "generatedStillRef": reference,
            "sourceFingerprint": source,
            "layerId": layer["layerId"],
            "placement": layer["placement"],
            "zOrder": layer["zOrder"],
            "layerRole": layer["role"],
        },
    }
    return workspace, job, layer, operation


def test_generated_still_proof_requires_exact_static_placement(card_proof):
    workspace, _, layer, operation = card_proof
    artcraft_stills.require_generated_still_layer(layer)
    graph = {"operations": [operation]}
    output = {"frameRate": {"num": 24, "den": 1}}
    locks = artcraft_stills.generated_still_locks(workspace, graph, output)
    assert locks == {"generated-still:vector-card": content_hash(operation)}
    shifted = deepcopy(operation)
    shifted["parameters"]["placement"]["x"] += 1
    with pytest.raises(ValueError, match="canonical Tracks"):
        artcraft_stills.generated_still_locks(
            workspace, {"operations": [shifted]}, output
        )
    with pytest.raises(ValueError, match="exact proof binding"):
        artcraft_stills.resolve_generated_still_operation(shifted, locks)
    with pytest.raises(ValueError, match="Cut proof"):
        artcraft_stills.generated_still_locks(
            workspace, graph, output, checkpoint="cut-proof"
        )


def test_generated_still_cannot_inherit_dynamic_or_unclosed_source_behavior(card_proof):
    workspace, job, layer, operation = card_proof
    layer["generatedSourceRef"] = {"engine": "code-drawn"}
    with pytest.raises(ValueError, match="static overlay"):
        artcraft_stills.require_generated_still_layer(layer)
    del layer["generatedSourceRef"]
    dynamic = {**operation, "kind": "overlay-video"}
    output = {"frameRate": {"num": 24, "den": 1}}
    with pytest.raises(ValueError, match="static overlay-image"):
        artcraft_stills.generated_still_locks(
            workspace, {"operations": [dynamic]}, output
        )
    job["inputs"] = [{"locator": "external-prototype.fig"}]
    with pytest.raises(ValueError, match="external dependencies"):
        artcraft_stills.require_generated_still_layer(layer)


def test_generated_still_proof_rejects_a_foreign_video_and_svg_interchange(card_proof):
    workspace, job, layer, operation = card_proof
    context = {
        "kind": "video",
        "videoId": workspace.video_id,
        "project": str(workspace.project_path),
    }
    job["request"]["context"] = context
    graph = {"operations": [operation]}
    output = {"frameRate": {"num": 24, "den": 1}}
    assert artcraft_stills.generated_still_locks(workspace, graph, output)
    job["request"]["context"] = {**context, "videoId": "other-video"}
    with pytest.raises(TrackError, match="different video"):
        resolve_tracks({"videoTracks": {"layers": [layer]}}, set(), workspace=workspace)
    with pytest.raises(ValueError, match="different video"):
        artcraft_stills.generated_still_locks(workspace, graph, output)
    job["request"]["context"] = context
    job["output"]["format"] = "svg"
    with pytest.raises(ValueError, match="verified VectorCraft card"):
        artcraft_stills.require_generated_still_layer(layer)
