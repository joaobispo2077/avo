from __future__ import annotations

import copy

import pytest

from avo.timeline.contracts import ContractError, validate_document


def strategy_document():
    return {
        "schemaVersion": "1.0.0",
        "scope": "video",
        "videoId": "video",
        "provider": "bishop",
        "currentRevisionId": "animation-r0001",
        "revisions": [
            {
                "revisionId": "animation-r0001",
                "strategy": {
                    "formatDiagnosis": {
                        "format": "talking-head-review",
                        "viewerIntent": "decide",
                        "motionDensity": 2,
                    },
                    "density": 2,
                    "components": [
                        {
                            "componentId": "chapter-card",
                            "providerPatternRef": "c01-c02",
                            "lifecycle": {
                                "preEntry": "hidden",
                                "entrance": "tremble",
                                "hold": "readable",
                                "exit": "fade",
                            },
                            "accessibility": {"reducedMotion": "fade"},
                        }
                    ],
                    "safeZones": ["face-left", "captions"],
                    "accessibility": {"reducedMotion": True, "flashingSafe": True},
                    "dependencies": {
                        "cmap": "a" * 64,
                        "bmap": "b" * 64,
                        "tracks": "c" * 64,
                    },
                    "framework": "hyperframes",
                },
            }
        ],
    }


def test_video_animation_strategy_contract():
    validate_document(strategy_document(), "avo.animation.schema.json")


@pytest.mark.parametrize("field", ["start", "end", "timestamp", "timing"])
def test_video_animation_component_forbids_timing(field):
    document = copy.deepcopy(strategy_document())
    document["revisions"][0]["strategy"]["components"][0][field] = 100
    with pytest.raises(ContractError):
        validate_document(document, "avo.animation.schema.json")
