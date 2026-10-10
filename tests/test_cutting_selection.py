"""Selection consolidation preserves rejected gaps and original unit order."""

from copy import deepcopy

import pytest

from avo.timeline.cutting_service import CuttingServiceError, consolidate_removals


def unit(identity, start, end):
    return {
        "segmentId": identity,
        "sourceId": "raw",
        "in": {"ticks": start, "timebase": {"num": 1, "den": 1000}},
        "out": {"ticks": end, "timebase": {"num": 1, "den": 1000}},
    }


def removal(identity, start, end):
    return {
        "segmentId": identity,
        "removeRange": {
            "sourceId": "raw",
            "startTicks": start,
            "endTicksExclusive": end,
            "timebase": {"num": 1, "den": 1000},
        },
    }


def test_subtraction_never_bridges_discarded_source_material():
    original = {"segments": [unit("left", 0, 1000), unit("right", 2000, 3000)]}
    frozen = deepcopy(original)
    result = consolidate_removals(original, [removal("left", 600, 800)])
    assert [(s["in"]["ticks"], s["out"]["ticks"]) for s in result["segments"]] == [
        (0, 600),
        (800, 1000),
        (2000, 3000),
    ]
    assert original == frozen


@pytest.mark.parametrize(
    "edits",
    [
        [removal("left", 600, 1100)],
        [removal("left", 300, 700), removal("left", 600, 800)],
        [removal("unknown", 300, 700)],
    ],
)
def test_invalid_removal_never_creates_a_selection(edits):
    with pytest.raises(CuttingServiceError):
        consolidate_removals({"segments": [unit("left", 0, 1000)]}, edits)
