from copy import deepcopy

import pytest

from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService


@pytest.mark.parametrize(
    "service,collection,id_key,intent",
    [
        (CMapService, "segments", "segmentId", "preserve approved editorial meaning"),
        (BMapService, "cues", "cueId", "preserve beat intent on approved cut output"),
    ],
)
def test_diff_preserves_records_and_inputs(service, collection, id_key, intent):
    first = {id_key: "first", "value": 1}
    removed = {id_key: "removed", "value": 2}
    changed = {id_key: "first", "value": 3}
    added = {id_key: "added", "value": 4}
    parent = {collection: [first, removed]}
    child = {collection: [added, changed]}
    untouched = deepcopy((parent, child))
    operations = service._diff(parent, child, "repair")
    expected = [
        ("remove", "removed", {"before": removed}),
        ("add", "added", {"after": added}),
        ("replace", "first", {"before": first, "after": changed}),
        ("move", "first", {"fromOrder": 0, "toOrder": 1}),
    ]
    assert operations == [
        {
            "opId": f"diff-{index:04d}",
            "op": op,
            "target": {"collection": collection, "stableId": target},
            "reason": "repair",
            "actorIntent": intent,
            "affectedTimeRanges": [],
            **values,
        }
        for index, (op, target, values) in enumerate(expected, 1)
    ]
    assert (parent, child) == untouched
    assert service._diff(child, child, "unchanged") == []
    assert [op["op"] for op in service._diff(None, child, "initial")] == ["add", "add"]
