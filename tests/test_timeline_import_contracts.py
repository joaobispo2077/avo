from __future__ import annotations

from copy import deepcopy

import pytest

from avo.timeline.contracts import ContractError, validate_document
from avo.timeline.import_service import (
    _audio_selection,
    _output_settings,
    _selected_stream,
    _stream_selection,
)
from avo.timeline.otio_import import ImportError, exact_rate, packet_identity


def session():
    return {
        "schemaVersion": "1.0.0",
        "normalizerVersion": "1.0.0",
        "importId": "a" * 64,
        "provider": "channel",
        "videoId": "video",
        "state": "prepared",
        "source": {"sha256": "b" * 64, "sizeBytes": 12, "timelinePointer": ""},
        "options": {"mediaRoots": [], "mappings": {}, "declarations": {}},
        "refs": {},
        "expectedHeadHash": "empty",
        "actor": "editor",
        "reason": "Import existing work",
        "createdAt": "2026-11-02T00:00:00Z",
    }


def test_packet_identity_is_deterministic_and_scoped():
    first = packet_identity("a" * 64, "", "channel", "video", {})
    assert len(first) == 64
    assert first == packet_identity("a" * 64, "", "channel", "video", {})
    assert first != packet_identity("a" * 64, "", "other", "video", {})
    assert first != packet_identity("a" * 64, "/children/1", "channel", "video", {})
    assert first != packet_identity(
        "a" * 64, "", "channel", "video", {"mapping": "changed"}
    )


def test_session_schema_accepts_only_known_state_and_fields():
    value = session()
    validate_document(value, "avo.timeline-import.schema.json")
    for key, item in (
        ("state", "approved"),
        ("importId", "../outside"),
        ("unknown", True),
    ):
        broken = deepcopy(value)
        broken[key] = item
        with pytest.raises(ContractError):
            validate_document(broken, "avo.timeline-import.schema.json")


def test_source_mapping_requires_explicit_path_and_supported_state():
    name = "avo.timeline-import.schema.json#/$defs/sourceMapping"
    validate_document({"path": "/declared/original.mov", "status": "unresolved"}, name)
    with pytest.raises(ContractError):
        validate_document({"filename": "original.mov", "status": "verified"}, name)


def test_findings_cannot_approve_content():
    name = "avo.timeline-import.schema.json#/$defs/finding"
    value = {
        "code": "OTIO_MEDIA_MISSING",
        "scope": "/tracks/0",
        "message": "Missing",
        "blocking": True,
        "evidenceOrigin": "export",
        "remediation": "Relink original",
    }
    validate_document(value, name)
    value["approval"] = True
    with pytest.raises(ContractError):
        validate_document(value, name)


def test_canonical_import_origin_and_policy_are_strict():
    name = "avo.cmap.schema.json#/$defs/cmapSnapshot"
    value = {
        "sources": [
            {
                "sourceId": "camera",
                "kind": "raw",
                "fingerprint": {"sha256": "a" * 64, "sizeBytes": 1},
            }
        ],
        "segments": [
            {
                "segmentId": "clip-one",
                "sourceId": "camera",
                "in": {
                    "ticks": 0,
                    "timebase": {"num": 1, "den": 24},
                    "domain": "raw-source",
                    "sourceId": "camera",
                },
                "out": {
                    "ticks": 24,
                    "timebase": {"num": 1, "den": 24},
                    "domain": "raw-source",
                    "sourceId": "camera",
                },
                "reason": "Preserve",
            }
        ],
        "sourceAssemblyPolicy": "preserve-import",
        "importOutput": {
            "width": 128,
            "height": 96,
            "frameRate": {"num": 24, "den": 1},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "displayOrigin": None,
        },
        "originRef": {
            "importId": "a" * 64,
            "exportSha256": "b" * 64,
            "timelinePointer": "",
            "proposalSha256": "c" * 64,
            "capabilityVersion": "contiguous-1.0.0",
            "activationId": "d" * 64,
        },
    }
    validate_document(value, name)
    broken = deepcopy(value)
    broken["originRef"]["approval"] = True
    with pytest.raises(ContractError):
        validate_document(broken, name)
    broken = deepcopy(value)
    broken["sourceAssemblyPolicy"] = "normalize-import"
    with pytest.raises(ContractError):
        validate_document(broken, name)


def test_malformed_rate_interpretations_and_extreme_clocks_are_scoped():
    for rate, declaration in [
        (24, {"rateInterpretations": [1]}),
        ("1e999999", {}),
        ("NaN", {}),
    ]:
        with pytest.raises(ImportError):
            exact_rate(rate, declaration, "/clip")


@pytest.mark.parametrize("channels", [True, [0], [0, 0, 1]])
def test_stereo_channel_selection_requires_two_explicit_channels(channels):
    with pytest.raises(ImportError):
        _audio_selection(
            {
                "streamIndex": 1,
                "channels": channels,
                "sourceLayout": "stereo",
                "outputLayout": "stereo",
            },
            {"channels": 2, "sampleRate": 48000, "channelLayout": "stereo"},
            "/clip",
        )


def test_known_variable_frame_rate_cannot_qualify_as_matching_cfr():
    with pytest.raises(ImportError):
        _stream_selection(
            {
                "videoStreamIndex": 0,
                "audioSelection": {
                    "streamIndex": 1,
                    "channels": [0, 1],
                    "sourceLayout": "stereo",
                    "outputLayout": "stereo",
                },
            },
            {
                "streams": {
                    "video": [
                        {"index": 0, "frameRate": "24/1", "averageFrameRate": "12/1"}
                    ],
                    "audio": [
                        {
                            "index": 1,
                            "sampleRate": 48000,
                            "channels": 2,
                            "channelLayout": "stereo",
                        }
                    ],
                }
            },
            {"frameRate": {"num": 24, "den": 1}},
            "/clip",
        )


@pytest.mark.parametrize("output", [True, ["width"], [{"width": 128}]])
def test_malformed_output_declaration_is_structured(output):
    with pytest.raises(ImportError):
        _output_settings({"sourceOnly": True, "output": output})


def test_boolean_stream_index_and_unknown_sample_rate_cannot_be_ready():
    with pytest.raises(ImportError):
        _selected_stream({"audio": [{"index": 1}]}, True, "audio", "/clip")
    with pytest.raises(ImportError):
        _audio_selection(
            {
                "streamIndex": 1,
                "channels": [0, 1],
                "sourceLayout": "stereo",
                "outputLayout": "stereo",
            },
            {"channels": 2, "sampleRate": 0, "channelLayout": "stereo"},
            "/clip",
        )
