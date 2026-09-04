from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def test_provider_watch_override_is_optional_and_strict() -> None:
    schema = json.loads(
        (ROOT / "providers" / "avo.provider.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
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
