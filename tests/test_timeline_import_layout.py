from __future__ import annotations

from copy import deepcopy

import pytest

from avo.timeline.contracts import validate_document
from avo.timeline.lineage import LineageError, validate_cmap_snapshot
from avo.timeline.mapping import (
    MappingError,
    cmap_output_duration,
)
from avo.timeline.mapping import (
    cmap_output_to_raw as output_to_raw,
)
from avo.timeline.mapping import (
    cmap_raw_to_output as raw_to_output,
)


def raw_time(ticks, source_id="camera", *, den=24):
    return {
        "ticks": ticks,
        "timebase": {"num": 1, "den": den},
        "domain": "raw-source",
        "sourceId": source_id,
    }


def program_time(ticks):
    return {
        "ticks": ticks,
        "timebase": {"num": 1, "den": 24},
        "domain": "cmap-output",
    }


def _placement(placement_id, track_id, start, end, raw_end):
    return {
        "placementId": placement_id,
        "elementId": f"/tracks/children/0/children/{placement_id}",
        "trackId": track_id,
        "sourceId": "camera",
        "mediaKind": "video",
        "in": raw_time(0),
        "out": raw_time(raw_end),
        "start": program_time(start),
        "end": program_time(end),
        "enabled": True,
        "routing": {"videoStreamIndex": 0},
        "evidenceOrigin": "export",
    }


def placed_snapshot():
    """Two repeated base cuts and an overlapping upper video layer, no file I/O."""
    display_origin = {"value": "86400", "rate": "24"}
    return {
        "sources": [
            {
                "sourceId": "camera",
                "kind": "raw",
                "fingerprint": {"sha256": "a" * 64, "sizeBytes": 1},
            }
        ],
        "layoutMode": "placed",
        "sourceAssemblyPolicy": "preserve-import",
        "importOutput": {
            "width": 128,
            "height": 96,
            "frameRate": {"num": 24, "den": 1},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "displayOrigin": deepcopy(display_origin),
        },
        "originRef": {
            "importId": "a" * 64,
            "exportSha256": "b" * 64,
            "timelinePointer": "",
            "proposalSha256": "c" * 64,
            "capabilityVersion": "placed-1.0.0",
            "activationId": "d" * 64,
        },
        "layout": {
            "programClock": {
                "frameRate": {"num": 24, "den": 1},
                "timebase": {"num": 1, "den": 24},
                "audioSampleRate": 48000,
            },
            "duration": program_time(96),
            "displayOrigin": display_origin,
            "background": "black",
            "tracks": [
                {
                    "trackId": track_id,
                    "kind": "video",
                    "order": order,
                    "enabled": True,
                    "muted": False,
                    "evidenceOrigin": "export",
                }
                for order, track_id in enumerate(("v1", "v2"))
            ],
            "placements": [
                _placement("first", "v1", 24, 48, 24),
                _placement("repeat", "v1", 72, 96, 24),
                _placement("upper", "v2", 30, 42, 12),
            ],
            "gaps": [
                {
                    "gapId": gap_id,
                    "trackId": "v1",
                    "start": program_time(start),
                    "end": program_time(end),
                    "evidenceOrigin": "export",
                }
                for gap_id, start, end in (("opening", 0, 24), ("middle", 48, 72))
            ],
        },
    }


def legacy_snapshot():
    return {
        "sources": deepcopy(placed_snapshot()["sources"]),
        "segments": [
            {
                "segmentId": "legacy-cut",
                "sourceId": "camera",
                "in": raw_time(0),
                "out": raw_time(24),
                "reason": "Preserve original cut",
            }
        ],
    }


def test_placed_contract_accepts_cross_track_overlap_without_mutating_evidence():
    snapshot = placed_snapshot()
    before = deepcopy(snapshot)
    validate_cmap_snapshot(snapshot)
    validate_document(snapshot, "avo.cmap.schema.json#/$defs/cmapSnapshot")
    assert snapshot == before
    assert "segments" not in snapshot
    assert cmap_output_duration(snapshot) == 96


def test_legacy_contiguous_snapshot_and_mapping_remain_valid():
    snapshot = legacy_snapshot()
    validate_cmap_snapshot(snapshot)
    validate_document(snapshot, "avo.cmap.schema.json#/$defs/cmapSnapshot")
    assert cmap_output_duration(snapshot) == 24
    assert raw_to_output(snapshot, "camera", 5) == 5
    assert output_to_raw(snapshot, 5) == ("camera", 5)


def test_placed_and_contiguous_representations_are_mutually_exclusive():
    snapshot = placed_snapshot()
    snapshot["segments"] = legacy_snapshot()["segments"]
    with pytest.raises(LineageError):
        validate_cmap_snapshot(snapshot)


def test_repeated_raw_media_requires_a_placement_selector():
    snapshot = placed_snapshot()
    with pytest.raises(MappingError, match="ambig"):
        raw_to_output(snapshot, "camera", 5)
    assert raw_to_output(snapshot, "camera", 5, placement_id="first") == 29
    assert raw_to_output(snapshot, "camera", 5, placement_id="repeat") == 77
    assert raw_to_output(snapshot, "camera", 5, placement_id="upper") == 35


def test_track_selector_cannot_resolve_repeated_raw_occurrences_on_one_track():
    with pytest.raises(MappingError, match="ambig"):
        raw_to_output(placed_snapshot(), "camera", 5, track_id="v1")
    assert raw_to_output(placed_snapshot(), "camera", 5, track_id="v2") == 35


def test_layered_output_requires_a_track_or_placement_selector():
    snapshot = placed_snapshot()
    with pytest.raises(MappingError, match="ambig"):
        output_to_raw(snapshot, 35)
    assert output_to_raw(snapshot, 35, track_id="v1") == ("camera", 11)
    assert output_to_raw(snapshot, 35, track_id="v2") == ("camera", 5)
    assert output_to_raw(snapshot, 35, placement_id="upper") == ("camera", 5)


@pytest.mark.parametrize("point", [-1, 0, 10, 48, 60, 96, 97])
def test_placed_gaps_and_program_end_are_half_open(point):
    assert output_to_raw(placed_snapshot(), point) is None


def test_placed_clip_end_does_not_map_to_the_preceding_clip():
    snapshot = placed_snapshot()
    assert output_to_raw(snapshot, 42, track_id="v2") is None
    assert output_to_raw(snapshot, 72, track_id="v1") == ("camera", 0)
    assert raw_to_output(snapshot, "camera", 24, placement_id="first") is None


@pytest.mark.parametrize("disabled", ["track", "placement"])
def test_disabled_upper_layer_has_no_active_mapping(disabled):
    snapshot = placed_snapshot()
    target = (
        snapshot["layout"]["tracks"][1]
        if disabled == "track"
        else snapshot["layout"]["placements"][2]
    )
    target["enabled"] = False
    validate_cmap_snapshot(snapshot)
    assert output_to_raw(snapshot, 35) == ("camera", 11)
    assert raw_to_output(snapshot, "camera", 5, placement_id="upper") is None


def _set_path(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("layout", "duration", "ticks"), 95),
        (("layout", "duration", "ticks"), -1),
        (("layout", "placements", 0, "start", "ticks"), -1),
        (("layout", "placements", 0, "end", "ticks"), 24),
        (("layout", "placements", 2, "out", "ticks"), 13),
        (("layout", "placements", 0, "in", "ticks"), -1),
        (("layout", "placements", 0, "out", "ticks"), 0),
        (("layout", "placements", 0, "sourceId"), "missing-source"),
        (("layout", "placements", 0, "trackId"), "missing-track"),
        (("layout", "placements", 0, "in", "sourceId"), "other-source"),
        (("layout", "placements", 0, "in", "domain"), "cmap-output"),
        (("layout", "placements", 0, "start", "domain"), "raw-source"),
        (("layout", "placements", 0, "in", "timebase", "den"), 0),
        (("layout", "placements", 0, "routing", "videoStreamIndex"), True),
        (("layout", "programClock", "frameRate", "num"), 0),
        (("layout", "programClock", "frameRate", "den"), -1),
        (("layout", "programClock", "timebase", "num"), 0),
        (("layout", "programClock", "timebase", "den"), 0),
        (("layout", "programClock", "audioSampleRate"), 0),
        (("layout", "gaps", 0, "trackId"), "missing-track"),
        (("layout", "gaps", 0, "end", "ticks"), 0),
        (("layout", "gaps", 0, "start", "ticks"), -1),
        (("originRef", "approval"), True),
    ],
)
def test_placed_contract_rejects_bad_bounds_clocks_domains_and_references(
    path, replacement
):
    snapshot = placed_snapshot()
    _set_path(snapshot, path, replacement)
    with pytest.raises(LineageError):
        validate_cmap_snapshot(snapshot)


@pytest.mark.parametrize(
    "collection,key",
    [("tracks", "trackId"), ("placements", "placementId"), ("gaps", "gapId")],
)
def test_placed_ids_are_unique_within_each_collection(collection, key):
    snapshot = placed_snapshot()
    entries = snapshot["layout"][collection]
    entries[1][key] = entries[0][key]
    with pytest.raises(LineageError):
        validate_cmap_snapshot(snapshot)


def test_placed_sources_retain_unique_raw_fingerprinted_identity():
    for alteration in ("duplicate", "derived", "missing-hash"):
        snapshot = placed_snapshot()
        if alteration == "duplicate":
            snapshot["sources"].append(deepcopy(snapshot["sources"][0]))
        elif alteration == "derived":
            snapshot["sources"][0]["kind"] = "proxy"
        else:
            snapshot["sources"][0]["fingerprint"] = {}
        with pytest.raises(LineageError):
            validate_cmap_snapshot(snapshot)


@pytest.mark.parametrize("overlap", ["placement", "gap"])
def test_placed_intervals_cannot_overlap_on_the_same_track(overlap):
    snapshot = placed_snapshot()
    if overlap == "placement":
        snapshot["layout"]["placements"][2]["trackId"] = "v1"
    else:
        snapshot["layout"]["gaps"][0]["end"] = program_time(25)
    with pytest.raises(LineageError):
        validate_cmap_snapshot(snapshot)


def test_still_placement_holds_a_fingerprinted_frame_for_program_duration():
    snapshot = placed_snapshot()
    still = snapshot["layout"]["placements"][2]
    still["mediaKind"] = "still"
    still["out"] = raw_time(1)
    validate_cmap_snapshot(snapshot)
    validate_document(snapshot, "avo.cmap.schema.json#/$defs/cmapSnapshot")
    assert cmap_output_duration(snapshot) == 96


@pytest.mark.parametrize("treatment", [{}, {"gainDb": -3.0}, {"muted": False}])
def test_audio_placement_retains_explicit_routing_and_sample_clock_without_gain_defaults(
    treatment,
):
    snapshot = placed_snapshot()
    snapshot["layout"]["tracks"].append(
        {
            "trackId": "a1",
            "kind": "audio",
            "order": 0,
            "enabled": True,
            "muted": False,
            "evidenceOrigin": "export",
        }
    )
    audio = _placement("dialogue", "a1", 24, 48, 24)
    audio.update(
        mediaKind="audio",
        **{"in": raw_time(0, den=48000), "out": raw_time(48000, den=48000)},
        routing={
            "audioSelection": {
                "streamIndex": 1,
                "channels": [0, 1],
                "sourceLayout": "stereo",
                "outputLayout": "stereo",
                "sourceSampleRate": 48000,
            }
        },
    )
    audio.update(treatment)
    snapshot["layout"]["placements"].append(audio)
    before = deepcopy(snapshot)
    validate_cmap_snapshot(snapshot)
    validate_document(snapshot, "avo.cmap.schema.json#/$defs/cmapSnapshot")
    assert snapshot == before
    for field in ("gainDb", "muted"):
        assert (field in audio) == (field in treatment)
        assert audio.get(field) == treatment.get(field)
    assert output_to_raw(snapshot, 35, track_id="a1") == ("camera", 22000)
