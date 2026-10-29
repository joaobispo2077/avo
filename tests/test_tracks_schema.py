from __future__ import annotations

import unittest

import pytest

from avo.timeline.contracts import ContractError, validate_document

SHA = "a" * 64


def doc():
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "tracks",
        "artifactId": "assembly",
        "videoId": "v",
        "provider": "bishop",
        "timelineDomain": "cmap-output",
        "currentRevisionId": "r1",
        "approvedRevisionId": None,
        "revisions": [
            {
                "revisionId": "r1",
                "parentRevisionId": None,
                "createdAt": "2026-08-13T00:00:00Z",
                "actor": "agent",
                "reason": "assembly",
                "snapshot": {
                    "basis": {
                        "artifactType": "bmap",
                        "artifactId": "beats",
                        "revisionId": "b1",
                        "sha256": SHA,
                        "state": "valid",
                    },
                    "audioTracks": {
                        "layers": [
                            {
                                "layerId": "dialogue",
                                "order": 0,
                                "role": "dialogue",
                                "source": {
                                    "sha256": SHA,
                                    "sizeBytes": 1,
                                    "generator": "base-program",
                                },
                                "regions": [
                                    {
                                        "regionId": "region-dialogue",
                                        "startTicks": 0,
                                        "endTicks": 1000,
                                        "cueIds": ["q1"],
                                    }
                                ],
                                "channels": [0, 1],
                                "gainDb": 0,
                                "mute": False,
                                "loudnessIntent": "dialogue-lead",
                            }
                        ]
                    },
                    "videoTracks": {
                        "layers": [
                            {
                                "layerId": "base",
                                "order": 0,
                                "role": "base",
                                "source": {
                                    "sha256": SHA,
                                    "sizeBytes": 1,
                                    "generator": "base-program",
                                },
                                "regions": [
                                    {
                                        "regionId": "region-base",
                                        "startTicks": 0,
                                        "endTicks": 1000,
                                        "cueIds": ["q1"],
                                    }
                                ],
                                "zOrder": 0,
                                "fit": "contain",
                                "safeZones": ["face"],
                                "faceAvoidance": True,
                            }
                        ]
                    },
                },
                "diff": [],
                "dependencies": [],
                "contentHash": "b" * 64,
                "evidence": [],
                "state": "draft",
            }
        ],
        "decisions": [],
    }


class TracksSchemaTests(unittest.TestCase):
    def test_valid(self):
        validate_document(doc(), "avo.tracks.schema.json")

    def test_unknown_layer_field_rejected(self):
        d = doc()
        d["revisions"][0]["snapshot"]["audioTracks"]["layers"][0]["secret"] = 1
        with self.assertRaises(ContractError):
            validate_document(d, "avo.tracks.schema.json")


def generated_tracks_document():
    document = doc()
    layer = document["revisions"][0]["snapshot"]["videoTracks"]["layers"][0]
    layer.pop("source")
    layer["generatedSourceRef"] = {
        "engine": "code-drawn",
        "instanceId": "drawing-one",
        "manifestRef": {
            "path": "edit/derived/components/drawing-one/source-r0001/composition.json",
            "sha256": SHA,
        },
    }
    return document, layer


def test_generated_video_layer_references_source_before_output_exists():
    document, layer = generated_tracks_document()
    validate_document(document, "avo.tracks.schema.json")
    assert "source" not in layer
    assert set(layer["generatedSourceRef"]) == {"engine", "instanceId", "manifestRef"}
    assert (
        layer["regions"]
        == doc()["revisions"][0]["snapshot"]["videoTracks"]["layers"][0]["regions"]
    )


def test_generated_video_layer_can_declare_the_matching_adapter():
    document, layer = generated_tracks_document()
    layer["generator"] = {"adapterId": "code-drawn"}
    validate_document(document, "avo.tracks.schema.json")


def test_generated_video_layer_cannot_also_claim_an_original_source():
    document, layer = generated_tracks_document()
    layer["source"] = doc()["revisions"][0]["snapshot"]["videoTracks"]["layers"][0][
        "source"
    ]
    with pytest.raises(ContractError):
        validate_document(document, "avo.tracks.schema.json")


@pytest.mark.parametrize("adapter", ["hyperframes", "remotion", "other", None])
def test_generated_video_layer_rejects_a_conflicting_optional_generator(adapter):
    document, layer = generated_tracks_document()
    layer["generator"] = {"adapterId": adapter}
    with pytest.raises(ContractError):
        validate_document(document, "avo.tracks.schema.json")


@pytest.mark.parametrize("engine", ["hyperframes", "remotion", "canvas", None])
def test_code_drawn_generated_source_reference_rejects_other_engines(engine):
    document, layer = generated_tracks_document()
    layer["generatedSourceRef"]["engine"] = engine
    with pytest.raises(ContractError):
        validate_document(document, "avo.tracks.schema.json")


@pytest.mark.parametrize("field", ["engine", "instanceId", "manifestRef"])
def test_generated_video_layer_requires_the_complete_logical_reference(field):
    document, layer = generated_tracks_document()
    layer["generatedSourceRef"].pop(field)
    with pytest.raises(ContractError):
        validate_document(document, "avo.tracks.schema.json")


@pytest.mark.parametrize(
    "field", ["startTicks", "endTicks", "outputHash", "recordHash", "generatedAssetRef"]
)
def test_generated_source_reference_cannot_add_timing_or_future_receipt_authority(
    field,
):
    document, layer = generated_tracks_document()
    layer["generatedSourceRef"][field] = SHA
    with pytest.raises(ContractError):
        validate_document(document, "avo.tracks.schema.json")


def test_generated_video_reference_is_not_an_audio_source_contract():
    document, layer = generated_tracks_document()
    audio = document["revisions"][0]["snapshot"]["audioTracks"]["layers"][0]
    audio["generatedSourceRef"] = layer["generatedSourceRef"]
    with pytest.raises(ContractError):
        validate_document(document, "avo.tracks.schema.json")


def test_historical_tracks_sources_and_generator_metadata_are_byte_stable():
    from avo.timeline.contracts import canonical_json_bytes

    document = doc()
    layer = document["revisions"][0]["snapshot"]["videoTracks"]["layers"][0]
    layer["generator"] = {"adapterId": "historical-generator", "legacyOption": True}
    before = canonical_json_bytes(document)
    validate_document(document, "avo.tracks.schema.json")
    assert canonical_json_bytes(document) == before


@pytest.mark.parametrize("generator", [{}, {"engine": "code-drawn"}])
def test_generated_video_optional_generator_requires_its_adapter_id(generator):
    document, layer = generated_tracks_document()
    layer["generator"] = generator
    with pytest.raises(ContractError):
        validate_document(document, "avo.tracks.schema.json")
