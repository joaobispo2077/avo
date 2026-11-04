from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.timeline import mapping
from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService
from avo.timeline.cutting_service import CuttingService, CuttingServiceError
from avo.timeline.lineage import LineageError
from tests.test_timeline_bmap_service import cue
from tests.test_timeline_import_layout import (
    legacy_snapshot,
    placed_snapshot,
    program_time,
    raw_time,
)


@pytest.mark.parametrize(
    "factory,expected",
    [
        (placed_snapshot, {"num": 1, "den": 24}),
        (legacy_snapshot, {"num": 1, "den": 24}),
    ],
)
def test_shared_output_timebase_uses_program_clock_and_returns_detached_value(
    factory, expected
):
    snapshot = factory()
    original = deepcopy(snapshot)
    base = mapping.cmap_output_timebase(snapshot)
    assert base == expected
    base["den"] = 999
    assert snapshot == original


@pytest.mark.parametrize(
    "start,end,den", [(30, 42, 24), (60000, 84000, 48000), (0, 12, 24)]
)
def test_bmap_validates_against_placed_program_clock_including_black_gaps(
    start, end, den
):
    value = cue()
    value["start"] = {
        "ticks": start,
        "timebase": {"num": 1, "den": den},
        "domain": "cmap-output",
    }
    value["end"] = {
        "ticks": end,
        "timebase": {"num": 1, "den": den},
        "domain": "cmap-output",
    }
    basis = {"revisionId": "placed"}
    BMapService._validate_snapshot(
        {"basis": basis, "cues": [value]}, basis, {"snapshot": placed_snapshot()}
    )


def test_bmap_placed_cue_cannot_extend_beyond_exact_program_duration():
    value = cue()
    value["start"], value["end"] = program_time(72), program_time(97)
    basis = {"revisionId": "placed"}
    with pytest.raises(LineageError, match="outside"):
        BMapService._validate_snapshot(
            {"basis": basis, "cues": [value]}, basis, {"snapshot": placed_snapshot()}
        )


def _change(snapshot, path, value):
    for key in path[:-1]:
        snapshot = snapshot[key]
    snapshot[path[-1]] = value


@pytest.mark.parametrize(
    "path,value,collection,stable_id",
    [
        (("layout", "placements", 0, "enabled"), False, "layout.placements", "first"),
        (("layout", "tracks", 1, "enabled"), False, "layout.tracks", "v2"),
        (("layout", "gaps", 1, "end", "ticks"), 70, "layout.gaps", "middle"),
        (("layout", "duration", "ticks"), 120, "settings", "layout.duration"),
        (
            ("layout", "programClock", "audioSampleRate"),
            44100,
            "settings",
            "layout.programClock",
        ),
        (("layout", "displayOrigin", "value"), "0", "settings", "layout.displayOrigin"),
        (("importOutput", "width"), 256, "settings", "importOutput"),
        (("originRef", "proposalSha256"), "e" * 64, "settings", "originRef"),
        (("sources", 0, "fingerprint", "sha256"), "f" * 64, "sources", "camera"),
    ],
)
def test_cmap_placed_diff_records_stable_layout_and_setting_changes(
    path, value, collection, stable_id
):
    parent = placed_snapshot()
    child = deepcopy(parent)
    _change(child, path, value)
    changes = CMapService._diff(parent, child, "Preserve imported edit")
    match = [
        item
        for item in changes
        if item["target"] == {"collection": collection, "stableId": stable_id}
    ]
    assert len(match) == 1
    assert match[0]["op"] == "replace"
    assert match[0]["before"] != match[0]["after"]
    assert match[0]["reason"] == "Preserve imported edit"
    assert len({item["opId"] for item in changes}) == len(changes)


def test_cmap_placed_creation_and_reordering_have_replayable_unique_operations():
    snapshot = placed_snapshot()
    creation = CMapService._diff(None, snapshot, "Import")
    assert {
        item["target"]["stableId"]
        for item in creation
        if item["target"]["collection"] == "layout.placements"
    } == {"first", "repeat", "upper"}
    assert len({item["opId"] for item in creation}) == len(creation)
    assert CMapService._diff(snapshot, deepcopy(snapshot), "Unchanged") == []
    changed = deepcopy(snapshot)
    changed["layout"]["placements"] = list(reversed(changed["layout"]["placements"]))
    operations = CMapService._diff(snapshot, changed, "Reorder evidence")
    assert operations and all(item["op"] == "move" for item in operations)
    assert {item["target"]["stableId"] for item in operations} == {"first", "upper"}


def test_cmap_legacy_diff_stays_segment_based():
    parent = legacy_snapshot()
    child = deepcopy(parent)
    child["segments"][0]["reason"] = "Updated editorial reason"
    changes = CMapService._diff(parent, child, "Explain")
    assert len(changes) == 1
    assert changes[0]["target"] == {"collection": "segments", "stableId": "legacy-cut"}
    assert changes[0]["op"] == "replace"


def _cutting_current(snapshot):
    revision = {"revisionId": "placed", "snapshot": snapshot}
    store = SimpleNamespace(
        load_index=lambda: {"headRevisionId": "placed"}, revision=lambda _: revision
    )
    service = CuttingService.__new__(CuttingService)
    service.workspace = SimpleNamespace(authority="canonical", store=lambda _: store)
    return service, revision


@pytest.mark.parametrize("mixed", [False, True, "unmarked"])
def test_automated_cutting_rejects_placed_before_legacy_or_media_access(
    monkeypatch, mixed
):
    snapshot = placed_snapshot()
    if mixed:
        snapshot["segments"] = legacy_snapshot()["segments"]
    if mixed == "unmarked":
        snapshot.pop("layoutMode")
    service, _ = _cutting_current(snapshot)
    monkeypatch.setattr(
        CMapService,
        "_verify_raw",
        lambda *_: pytest.fail("placed raw access must not run"),
    )
    with pytest.raises(CuttingServiceError, match="placed"):
        service._current()


def test_automated_cutting_legacy_current_keeps_raw_verification(monkeypatch):
    service, revision = _cutting_current(legacy_snapshot())
    observed = []
    monkeypatch.setattr(
        CMapService, "_verify_raw", lambda _, snapshot: observed.append(snapshot)
    )
    assert service._current() == revision
    assert observed == [revision["snapshot"]]


def _mixed_source_clocks():
    snapshot = placed_snapshot()
    repeated = snapshot["layout"]["placements"][1]
    repeated["in"], repeated["out"] = raw_time(0, den=48), raw_time(48, den=48)
    return snapshot


def test_placed_raw_ticks_cannot_implicitly_switch_between_source_clocks():
    snapshot = _mixed_source_clocks()
    with pytest.raises(mapping.MappingError, match="clock"):
        mapping.cmap_raw_to_output(snapshot, "camera", 24)
    assert (
        mapping.cmap_raw_to_output(
            snapshot, "camera", 24, raw_timebase={"num": 1, "den": 24}
        )
        is None
    )
    assert (
        mapping.cmap_raw_to_output(snapshot, "camera", 24, placement_id="repeat") == 84
    )
    assert (
        mapping.cmap_raw_to_output(
            snapshot,
            "camera",
            24,
            placement_id="first",
            raw_timebase={"num": 1, "den": 48},
        )
        == 36
    )


def test_legacy_repeated_raw_source_also_requires_an_explicit_clock_when_mixed():
    snapshot = legacy_snapshot()
    repeated = deepcopy(snapshot["segments"][0])
    repeated.update(
        segmentId="repeated", **{"in": raw_time(0, den=48), "out": raw_time(48, den=48)}
    )
    snapshot["segments"].append(repeated)
    with pytest.raises(mapping.MappingError, match="clock"):
        mapping.cmap_raw_to_output(snapshot, "camera", 12)
    assert (
        mapping.cmap_raw_to_output(
            snapshot, "camera", 12, raw_timebase={"num": 1, "den": 48}
        )
        == 6
    )


def test_equivalent_rational_source_timebases_do_not_create_false_clock_ambiguity():
    snapshot = placed_snapshot()
    snapshot["layout"]["placements"][1]["enabled"] = False
    upper = snapshot["layout"]["placements"][2]
    for value in (upper["in"], upper["out"]):
        value["timebase"] = {"num": 2, "den": 48}
    assert mapping.cmap_raw_to_output(snapshot, "camera", 15) == 39
