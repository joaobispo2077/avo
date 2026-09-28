from __future__ import annotations

import pytest

from avo.adapters.understand.watch_skill import probe_vision_capabilities
from avo.timeline.vision_review import VisionReviewError, build_capability_snapshot


def _probe(**overrides):
    return {
        "servedModel": "qwen3.5-4b",
        "supportsVision": True,
        "effectiveContextTokens": 32_768,
        "maxOutputTokens": 2_048,
        "maxImages": 24,
        "detailModes": ["low", "high"],
        "requestHash": "a" * 64,
        "responseHash": "b" * 64,
        "probedAt": "2026-09-27T12:00:00Z",
        "latencyMs": 12.5,
        "success": True,
        **overrides,
    }


def test_snapshot_requires_exact_live_served_identity_and_vision() -> None:
    snapshot = build_capability_snapshot(
        configured_model="qwen3.5-4b",
        endpoint_identity={
            "providerType": "openai-compatible",
            "redactedBase": "local",
        },
        probe=_probe(),
        resource_policy={
            "device": "cuda:0",
            "vramCeilingBytes": 7 * 1024**3,
            "concurrency": 1,
            "operatorManagedLifecycle": True,
            "allowedCoResidency": ["cpu-transcription"],
        },
    )
    assert snapshot["servedModel"] == "qwen3.5-4b"
    assert snapshot["contextProvenance"] == "runtime-observed"
    assert len(snapshot["identityHash"]) == 64
    repeated = build_capability_snapshot(
        configured_model="qwen3.5-4b",
        endpoint_identity={
            "providerType": "openai-compatible",
            "redactedBase": "local",
        },
        probe=_probe(),
        resource_policy=snapshot["resourcePolicy"],
    )
    assert repeated["identityHash"] == snapshot["identityHash"]

    with pytest.raises(VisionReviewError, match="served model"):
        build_capability_snapshot(
            configured_model="qwen3.5-4b",
            endpoint_identity={
                "providerType": "openai-compatible",
                "redactedBase": "local",
            },
            probe=_probe(servedModel="another-model"),
            resource_policy=snapshot["resourcePolicy"],
        )


def test_unknown_runtime_context_requires_explicit_conservative_limit() -> None:
    kwargs = {
        "configured_model": "qwen3.5-4b",
        "endpoint_identity": {
            "providerType": "openai-compatible",
            "redactedBase": "local",
        },
        "probe": _probe(effectiveContextTokens=None),
        "resource_policy": {
            "device": "cuda:0",
            "vramCeilingBytes": 7 * 1024**3,
            "concurrency": 1,
            "operatorManagedLifecycle": True,
            "allowedCoResidency": [],
        },
    }
    with pytest.raises(VisionReviewError, match="context"):
        build_capability_snapshot(**kwargs)
    limited = build_capability_snapshot(**kwargs, conservative_context_limit=8_192)
    assert limited["effectiveContextTokens"] == 8_192
    assert limited["contextProvenance"] == "policy-conservative-limit"


def test_endpoint_pin_is_live_probed_and_endpoint_failure_blocks() -> None:
    pin = {
        "id": "qwen3.5-4b",
        "source": {
            "kind": "endpoint",
            "endpoint": {
                "baseUrl": "http://127.0.0.1:1234/v1",
                "servedName": "qwen3.5-4b",
            },
        },
    }
    policy = {
        "device": "cuda:0",
        "vramCeilingBytes": 7 * 1024**3,
        "concurrency": 1,
        "operatorManagedLifecycle": True,
        "allowedCoResidency": [],
    }
    calls = []

    def live_probe(base_url: str, served_name: str):
        calls.append((base_url, served_name))
        return _probe()

    snapshot = probe_vision_capabilities(
        model_pin=pin, probe=live_probe, resource_policy=policy
    )
    assert calls == [("http://127.0.0.1:1234/v1", "qwen3.5-4b")]
    assert snapshot["endpointIdentity"]["redactedBase"] == "http://<endpoint>/v1"

    with pytest.raises(VisionReviewError, match="probe failed"):
        probe_vision_capabilities(
            model_pin=pin,
            probe=lambda *_: _probe(success=False),
            resource_policy=policy,
        )
