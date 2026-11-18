"""Visual planning reuse never substitutes for current canonical/approval checks."""

from copy import deepcopy

import pytest

from avo.timeline.motion_scope import unchanged_visual_items, visual_roots_match


def roots():
    expected = {
        name: {
            "revisionId": name + "-original",
            "sha256": "a" * 64,
            "activeState": "valid",
            "approvedRevisionId": None,
        }
        for name in ("cmap", "bmap", "tracks", "animation")
    }
    expected["sync-map"] = None
    current = deepcopy(expected)
    for name in ("bmap", "tracks"):
        current[name].update(revisionId=name + "-audio", sha256="b" * 64)
    current["animation"]["activeState"] = "stale"
    return expected, current


def test_only_the_unchanged_animation_may_remain_dependency_stale():
    expected, current = roots()
    assert visual_roots_match(expected, current)
    assert current["animation"]["activeState"] == "stale"


@pytest.mark.parametrize(
    "name,field,value",
    [
        ("cmap", "revisionId", "changed-source"),
        ("cmap", "sha256", "c" * 64),
        ("cmap", "approvedRevisionId", "different-approval"),
        ("cmap", "activeState", "stale"),
        ("animation", "revisionId", "new-identical-body"),
        ("animation", "sha256", "c" * 64),
        ("animation", "activeState", "blocked"),
        ("animation", "activeState", "superseded"),
        ("animation", "availability", "unavailable"),
        ("bmap", "activeState", "stale"),
        ("tracks", "activeState", "stale"),
    ],
)
def test_changed_root_or_unreconciled_owner_blocks_visual_reuse(name, field, value):
    expected, current = roots()
    current[name][field] = value
    assert not visual_roots_match(expected, current)


@pytest.mark.parametrize("name", ["cmap", "tracks", "animation"])
def test_missing_or_unavailable_current_basis_is_not_reusable(name):
    expected, current = roots()
    current[name] = None
    assert not visual_roots_match(expected, current)


def test_changed_or_removed_sync_basis_blocks_reuse():
    expected, current = roots()
    current["sync-map"] = deepcopy(expected["cmap"])
    assert not visual_roots_match(expected, current)
    expected["sync-map"] = deepcopy(current["sync-map"])
    assert visual_roots_match(expected, current)
    current["sync-map"]["sha256"] = "c" * 64
    assert not visual_roots_match(expected, current)
    current["sync-map"] = None
    assert not visual_roots_match(expected, current)


def visual_metadata():
    return {
        "bmap": {
            "basis": {"sha256": "a" * 64},
            "cues": [
                {
                    "cueId": "graphic",
                    "kind": "animation",
                    "contentRef": {"itemId": "mo04"},
                    "start": {"ticks": 0},
                    "assetRef": {"sha256": "a" * 64},
                    "targetLayerId": "overlay",
                }
            ],
        },
        "tracks": {
            "basis": {"sha256": "a" * 64},
            "audioTracks": {"layers": [{"layerId": "dialogue"}]},
            "videoTracks": {"layers": [{"layerId": "overlay", "zOrder": 1}]},
        },
        "animation": {"components": [{"componentId": "graphic", "camera": [0, 1]}]},
    }


def proposal():
    return {
        "items": [
            {"itemId": "mo04", "disposition": "applied"},
            {"itemId": "unapplied", "disposition": "selected"},
            {"itemId": "missing-cue", "disposition": "applied"},
        ]
    }


def test_audio_changes_reuse_only_applied_timed_direction_without_mutating_inputs():
    original = visual_metadata()
    current = deepcopy(original)
    current["bmap"]["cues"].append({"cueId": "sfx-one", "kind": "sfx"})
    current["tracks"]["audioTracks"]["layers"].append({"layerId": "sfx-one"})
    current["tracks"]["basis"]["sha256"] = "b" * 64
    before = deepcopy((original, current))
    assert unchanged_visual_items(proposal(), original, current) == ["mo04"]
    assert (original, current) == before


def test_unique_explicit_cue_link_preserves_legacy_timed_direction():
    original = visual_metadata()
    original["bmap"]["cues"][0]["contentRef"] = {"text": "Legacy cue"}
    current = deepcopy(original)
    current["bmap"]["cues"].append({"cueId": "sfx-one", "kind": "sfx"})
    selected = proposal()
    selected["items"][0]["cueId"] = "graphic"
    assert unchanged_visual_items(selected, original, current) == ["mo04"]


@pytest.mark.parametrize("clean_part", [False, True])
def test_conflicting_cue_claim_cannot_preserve_any_affected_item(clean_part):
    original = visual_metadata()
    selected = {
        "items": [
            {"itemId": "mo04", "disposition": "applied"},
            {"itemId": "mo05", "disposition": "applied", "cueId": "graphic"},
        ]
    }
    if clean_part:
        original["bmap"]["cues"].append(
            {**deepcopy(original["bmap"]["cues"][0]), "cueId": "clean-part"}
        )
        selected["items"][0]["cueId"] = "clean-part"
    assert unchanged_visual_items(selected, original, deepcopy(original)) == []


@pytest.mark.parametrize(
    "change",
    ["timing", "asset", "layer", "removed", "new-visual", "order", "camera", "global"],
)
def test_changed_visual_dependency_blocks_reuse_of_the_assembly(change):
    original = visual_metadata()
    current = deepcopy(original)
    cue = current["bmap"]["cues"][0]
    if change == "timing":
        cue["start"]["ticks"] = 1
    elif change == "asset":
        cue["assetRef"]["sha256"] = "b" * 64
    elif change == "layer":
        cue["targetLayerId"] = "other"
    elif change == "removed":
        current["bmap"]["cues"] = []
    elif change == "new-visual":
        current["bmap"]["cues"].append({"cueId": "new", "kind": "text"})
    elif change == "order":
        current["tracks"]["videoTracks"]["layers"][0]["zOrder"] = 2
    elif change == "camera":
        current["animation"]["components"][0]["camera"] = [1, 0]
    else:
        current["bmap"]["newRenderSetting"] = True
    assert unchanged_visual_items(proposal(), original, current) == []
