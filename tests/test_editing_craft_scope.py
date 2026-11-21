"""Selected production windows keep one owner and complete dependency context."""

from copy import deepcopy

import pytest

from tests.test_timeline_bmap_service import cue


def scope(*selected):
    return {
        "clock": {"frameRate": {"num": 24, "den": 1}, "programEndFrame": 30},
        "chunks": [
            {"chunkId": "opening", "startFrame": 0, "endFrameExclusive": 10},
            {"chunkId": "middle", "startFrame": 10, "endFrameExclusive": 20},
            {"chunkId": "ending", "startFrame": 20, "endFrameExclusive": 30},
        ],
        "selectedChunkIds": list(selected),
    }


def part(identity, first, last, *, denominator=24):
    def at(ticks):
        return {
            "ticks": ticks,
            "timebase": {"num": 1, "den": denominator},
            "domain": "cmap-output",
        }

    canonical = cue()
    canonical.update(
        cueId=identity, start=at(first), end=at(last), targetLayerId="picture"
    )
    return {
        "cueId": identity,
        "timing": {"start": at(first), "end": at(last)},
        "targetLayerId": "picture",
        "componentRef": None,
        "cue": canonical,
    }


def item(identity, *parts):
    return {"itemId": identity, "parts": list(parts), "identityConflicts": []}


def build(items, request):
    from avo.timeline.craft_scope import build_scope_plan

    return build_scope_plan(
        items,
        request,
        basis_heads=dict.fromkeys(("cmap", "bmap", "tracks", "animation", "sync-map")),
    )


def test_cross_boundary_item_has_one_start_owner_and_untouched_context():
    items = [
        item("crossing", part("crossing-cue", 5, 15)),
        item("owned", part("owned-cue", 10, 12)),
        item("before", part("before-cue", 0, 10)),
        item("after", part("after-cue", 20, 25)),
    ]
    original = deepcopy(items)
    result = build(items, scope("middle"))
    assert [row["itemId"] for row in result["production"]] == ["owned"]
    assert [row["itemId"] for row in result["context"]] == ["crossing"]
    assert result["context"][0]["ownerChunkId"] == "opening"
    assert result["context"][0]["consumerChunkIds"] == ["middle"]
    assert result["context"][0]["parts"] == items[0]["parts"]
    assert result["outsideItemIds"] == ["before", "after"]
    assert result["approval"] == "not-granted"
    assert items == original


def test_split_item_is_accounted_once_across_all_intersecting_selected_chunks():
    split = item("split", part("first", 5, 8), part("later", 15, 25))
    context = build([split], scope("middle", "ending"))
    assert context["production"] == []
    assert len(context["context"]) == 1
    assert context["context"][0]["consumerChunkIds"] == ["middle", "ending"]
    assert context["context"][0]["parts"] == split["parts"]
    complete = build([split], scope("opening", "middle", "ending"))
    assert len(complete["production"]) == 1
    assert complete["context"] == []
    assert complete["production"][0]["ownerChunkId"] == "opening"


def test_fractional_canonical_start_is_not_rounded_into_the_next_owner():
    # 39/96 seconds is 9.75 frames at 24 fps, before the chunk boundary.
    value = item("fractional", part("fractional-cue", 39, 43, denominator=96))
    result = build([value], scope("middle"))
    assert result["production"] == []
    assert result["context"][0]["ownerChunkId"] == "opening"
    assert result["context"][0]["canonicalStartFrame"] == {"num": 39, "den": 4}


def test_untimed_or_ambiguous_items_never_gain_production_ownership():
    ambiguous = item("ambiguous", part("cue-one", 2, 5))
    ambiguous["identityConflicts"] = [{"itemId": "ambiguous"}]
    result = build([item("untimed"), ambiguous], scope("opening"))
    assert result["production"] == result["context"] == []
    assert result["unresolvedItemIds"] == ["untimed", "ambiguous"]
    assert result["complete"] is False


@pytest.mark.parametrize(
    "problem", ["gap", "overlap", "order", "missing-end", "unknown", "duplicate"]
)
def test_invalid_chunk_partition_or_selection_fails_instead_of_losing_work(problem):
    request = scope("opening")
    if problem == "gap":
        request["chunks"][1]["startFrame"] = 11
    elif problem == "overlap":
        request["chunks"][1]["startFrame"] = 9
    elif problem == "order":
        request["chunks"].reverse()
    elif problem == "missing-end":
        request["chunks"][-1]["endFrameExclusive"] = 29
    elif problem == "unknown":
        request["selectedChunkIds"] = ["unknown"]
    else:
        request["chunks"][1]["chunkId"] = "opening"
    with pytest.raises(ValueError):
        build([item("one", part("one-cue", 2, 5))], request)


def test_duplicate_item_or_cue_identity_cannot_count_a_contribution_twice():
    first = item("one", part("same-cue", 2, 5))
    with pytest.raises(ValueError):
        build([first, deepcopy(first)], scope("opening"))
    second = item("two", part("same-cue", 15, 18))
    with pytest.raises(ValueError):
        build([first, second], scope("opening", "middle"))


def test_context_window_and_split_seeks_keep_the_original_camera_phase():
    from tests.test_camera_evaluator import behavior, node, sample

    source = item("camera", part("camera-cue", 5, 25))
    selected = build([source], scope("middle"))
    original = selected["context"][0]["parts"][0]["timing"]
    first, last = original["start"]["ticks"], original["end"]["ticks"]
    path = behavior([node(0, 1.1, curve="quadratic-in-out"), node(1, 1.7)])
    full = {
        frame: sample(path, frame, first=first, end=last)
        for frame in range(first, last)
    }
    order = [19, 10, 15, 11, 18, 12]
    assert [sample(path, frame, first=first, end=last) for frame in order] == [
        full[frame] for frame in order
    ]
    assert full[10]["scale"] > 1.1
    assert selected["production"] == []
    assert (first, last) == (5, 25)
