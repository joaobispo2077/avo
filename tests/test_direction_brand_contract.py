"""Authored provider brand is frozen as data, never rewritten."""

import pytest

from avo.direction.rules import DirectionError, seal, validate


def test_brand_snapshot_has_exact_source_and_native_identity():
    value = seal(
        "BrandGuideSnapshot",
        {
            "provider": "neutral",
            "text": "Preserve authored brand authority.",
            "source": {"path": "DESIGN.md", "byteHash": "a" * 64},
            "normalizationVersion": "1.0.0",
        },
        clock=lambda: "2026-10-16T12:00:00Z",
    )
    assert value["source"]["path"] == "DESIGN.md"
    assert value["createdBy"]["type"] == "native"
    validate("BrandGuideSnapshot", value)


def test_brand_snapshot_rejects_media_locator_and_execution_fields():
    with pytest.raises(DirectionError):
        seal(
            "BrandGuideSnapshot",
            {
                "provider": "neutral",
                "text": "A reference",
                "source": {"path": "../private.mp4", "byteHash": "a" * 64},
                "normalizationVersion": "1.0.0",
                "execute": True,
            },
        )
