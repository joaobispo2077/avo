"""Neutral inputs and activity observations for optional ArtCraft tests."""

from collections import Counter

ACTIVITIES = ("probe", "launch", "connect", "fetch_docs", "load_guide")


class ArtCraftActivity:
    def __init__(self, *, permitted=()):
        self.permitted = frozenset(permitted)
        self.calls = Counter(dict.fromkeys(ACTIVITIES, 0))

    def record(self, activity):
        assert activity in ACTIVITIES
        self.calls[activity] += 1
        assert activity in self.permitted, f"unexpected ArtCraft activity: {activity}"


def request(**changes):
    return {
        "version": 1,
        "requestId": "lower-third-request",
        "provider": "neutral-channel",
        "componentId": "speaker-label",
        "purpose": "Identify the speaker during an introduction.",
        "context": {"kind": "provider-only"},
        "required": {
            "behavior": "editable-lower-third",
            "outputRole": "overlay-video",
            "editable": True,
        },
        "exclusions": [],
        "candidates": [],
        **changes,
    }


def picture_output(**changes):
    return {
        "role": "overlay-video",
        "format": "png-sequence",
        "width": 1920,
        "height": 1080,
        "frameRate": {"numerator": 24000, "denominator": 1001},
        "frameCount": 72,
        "alpha": "straight",
        "color": "srgb",
        **changes,
    }


def executable_observation(path):
    return {
        "app": "anicraft",
        "platform": "windows",
        "release": "0.0-test",
        "mode": "cli",
        "executable": {"locator": str(path), "sizeBytes": 8, "sha256": "e" * 64},
        "operations": ["lower-third"],
    }
