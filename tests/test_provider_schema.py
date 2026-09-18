from __future__ import annotations

import json
from pathlib import Path

from jsonschema_support import validator_for

ROOT = Path(__file__).resolve().parents[1]


def test_provider_watch_override_is_optional_and_strict() -> None:
    schema = json.loads(
        (ROOT / "providers" / "avo.provider.schema.json").read_text(encoding="utf-8")
    )
    validator = validator_for(schema)
    base = {"name": "sample", "kind": "youtube", "media": {"rawRoot": "/media"}}
    valid = {
        **base,
        "routingOverrides": {
            "watch": {"device": "cuda:1", "maxFrames": 24, "riskNotes": ["faces"]}
        },
    }
    assert list(validator.iter_errors(valid)) == []
    invalid = {
        **base,
        "routingOverrides": {"watch": {"maxFrames": 0, "privatePreset": True}},
    }
    assert list(validator.iter_errors(invalid))


def test_provider_models_pin_rejects_api_key() -> None:
    schema = json.loads(
        (ROOT / "providers" / "avo.provider.schema.json").read_text(encoding="utf-8")
    )
    validator = validator_for(schema)
    base = {"name": "sample", "kind": "youtube", "media": {"rawRoot": "/media"}}
    valid = {**base, "models": {"understand": {"id": "qwen2.5-7b"}}}
    assert list(validator.iter_errors(valid)) == []
    leaked = {
        **base,
        "models": {
            "understand": {
                "id": "qwen2.5-7b",
                "source": {
                    "kind": "endpoint",
                    "endpoint": {"baseUrl": "http://127.0.0.1/v1", "apiKey": "sk"},
                },
            }
        },
    }
    assert list(validator.iter_errors(leaked))
