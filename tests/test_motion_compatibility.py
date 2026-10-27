"""Protect historical routing and serialized motion identities."""

from __future__ import annotations

from copy import deepcopy

import pytest

from avo.adapters.base import (
    load_routing_config,
    parse_routing_token,
    routing_token_for_job,
)
from avo.adapters.motion.hyperframes import HyperframesAdapter
from avo.adapters.registry import adapter_for_routing_suffix
from avo.paths import repo_root
from avo.timeline.contracts import (
    canonical_json_bytes,
    content_hash,
    document_hash_excluding,
    validate_document,
)
from avo.timeline.generated_assets import GeneratedAssetError, GeneratedAssetService
from tests.test_video_animation_schema import strategy_document

LEGACY_STRATEGY_HASH = (
    "b9681888f9278f62f01dca27fd20bf0b4945d99a04cb7a1f9948f2b5ce2133a3"
)
LEGACY_GENERATED_ASSET_HASH = (
    "1e45e0c54393020a9204628b93cecf56bdce51a2d2b4a97817df04cb69408731"
)


def _legacy_generated_asset() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "assetId": "asset-title-card",
        "role": "authored-graphic",
        "generator": {
            "adapterId": "hyperframes",
            "version": "0.7.109",
            "executableSha256": "a" * 64,
        },
        "parameters": {"title": "Legacy title"},
        "inputs": [],
        "sourceFree": True,
        "environment": {"platform": "historical-test", "dependencies": {}},
        "output": {
            "sha256": "b" * 64,
            "sizeBytes": 15,
            "locator": "edit/derived/components/title/title.mkv",
        },
        "reproducibility": "verified",
        "approvalReference": None,
        "recordHash": LEGACY_GENERATED_ASSET_HASH,
    }


def test_absent_motion_preference_preserves_hyperframes_default() -> None:
    config = load_routing_config(repo_root())
    original = canonical_json_bytes(config)

    token = routing_token_for_job(config, "motion", "local")
    _owner, suffix = parse_routing_token(token)

    assert token == "hyperframes"
    assert adapter_for_routing_suffix("motion", suffix) is HyperframesAdapter
    assert canonical_json_bytes(config) == original


@pytest.mark.parametrize(
    ("job", "label", "expected_token", "expected_adapter"),
    [
        ("transcribe", "local", "video-use+faster-whisper", "faster-whisper"),
        ("transcribe", "paid", "elevenlabs", "elevenlabs"),
        ("understand", "local", "watch-skill", "watch-skill"),
        ("memory", "local", "ai-memory", "ai-memory"),
        ("plan", "local", "speckit", "speckit"),
    ],
)
def test_non_motion_job_routing_remains_unchanged(
    job: str, label: str, expected_token: str, expected_adapter: str
) -> None:
    config = load_routing_config(repo_root())
    original = canonical_json_bytes(config)

    token = routing_token_for_job(config, job, label)
    _owner, suffix = parse_routing_token(token)

    assert token == expected_token
    assert adapter_for_routing_suffix(job, suffix).routing_id == expected_adapter
    assert canonical_json_bytes(config) == original


def test_legacy_hyperframes_strategy_keeps_serialized_identity() -> None:
    document = strategy_document()
    original = canonical_json_bytes(document)

    validated = validate_document(document, "avo.animation.schema.json")

    assert canonical_json_bytes(validated) == original
    assert canonical_json_bytes(document) == original
    assert content_hash(validated) == LEGACY_STRATEGY_HASH
    assert validated["revisions"][0]["strategy"]["framework"] == "hyperframes"


def test_legacy_hyperframes_asset_keeps_seal_and_validation_identity() -> None:
    document = _legacy_generated_asset()
    original = canonical_json_bytes(document)
    unsealed = deepcopy(document)
    unsealed.pop("schemaVersion")
    unsealed.pop("recordHash")
    caller_bytes = canonical_json_bytes(unsealed)

    sealed = GeneratedAssetService._seal(unsealed)
    validated = GeneratedAssetService._validate(sealed)

    assert canonical_json_bytes(unsealed) == caller_bytes
    assert canonical_json_bytes(validated) == original
    assert canonical_json_bytes(document) == original
    assert document_hash_excluding(validated, "recordHash") == (
        LEGACY_GENERATED_ASSET_HASH
    )


def test_legacy_generated_asset_rejects_changed_serialized_content() -> None:
    document = _legacy_generated_asset()
    document["parameters"]["title"] = "Changed after sealing"

    with pytest.raises(GeneratedAssetError, match="record hash mismatch"):
        GeneratedAssetService._validate(document)
