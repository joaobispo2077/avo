"""Source mix changes bind exact placed originals without changing the assembly."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.timeline.initial_cut_placed import _audio
from avo.timeline.source_mix import (
    SourceMixError,
    apply_source_mix_adjustments,
    validate_source_mix_adjustments,
)


def _time(ticks, source=None, *, den=48000):
    return {
        "ticks": ticks,
        "timebase": {"num": 1, "den": den},
        "domain": "raw-source" if source else "cmap-output",
        **({"sourceId": source} if source else {}),
    }


def _placement(name, source, start, *, mono=False, **extra):
    return {
        "placementId": name,
        "sourceId": source,
        "trackId": source,
        "mediaKind": "audio",
        "enabled": True,
        "in": _time(48000, source),
        "out": _time(144000, source),
        "start": _time(start),
        "end": _time(start + 96000),
        "routing": {
            "audioSelection": {
                "streamIndex": 1 if mono else 2,
                "channels": [0] if mono else [0, 1],
                "sourceLayout": "mono" if mono else "stereo",
                "outputLayout": "dual-mono" if mono else "stereo",
                "sourceSampleRate": 48000,
            }
        },
        **extra,
    }


@pytest.fixture
def assembly(tmp_path):
    snapshot = {
        "layoutMode": "placed",
        "sources": [
            {
                "sourceId": name,
                "kind": "raw",
                "locator": str(tmp_path / f"{name}.mkv"),
                "fingerprint": {"sha256": digest * 64, "sizeBytes": 123},
            }
            for name, digest in (("game", "a"), ("mic", "b"))
        ],
        "layout": {
            "tracks": [
                {"trackId": name, "kind": "audio", "enabled": True, "muted": False}
                for name in ("game", "mic")
            ],
            "placements": [
                _placement("game-first", "game", 0),
                _placement(
                    "microphone",
                    "mic",
                    0,
                    mono=True,
                    gainDb=-2,
                    audioPeakCeilingDbfs=-4.5,
                ),
                _placement("game-repeat", "game", 96000),
            ],
        },
    }
    base = _audio(
        snapshot,
        {item["sourceId"]: item for item in snapshot["sources"]},
        {item["trackId"]: item for item in snapshot["layout"]["tracks"]},
        SimpleNamespace(raw_dir=tmp_path),
        192000,
        None,
    )
    return snapshot, base


def _adjustment(snapshot, placement="game-first", **extra):
    item = next(
        p for p in snapshot["layout"]["placements"] if p["placementId"] == placement
    )
    selection = item["routing"]["audioSelection"]
    source = next(s for s in snapshot["sources"] if s["sourceId"] == item["sourceId"])
    return {
        "placementId": placement,
        "sourceId": item["sourceId"],
        "sourceSha256": source["fingerprint"]["sha256"],
        "streamIndex": selection["streamIndex"],
        "channels": deepcopy(selection["channels"]),
        "gainDeltaDb": -6,
        **extra,
    }


def _gain(graph, node):
    return next(
        op
        for op in graph["operations"]
        if op["kind"] == "gain" and op["parameters"]["nodeId"] == node
    )


def _apply(assembly, adjustments, *, graph=None, require_applied=False):
    snapshot, base = assembly
    return apply_source_mix_adjustments(
        snapshot,
        base,
        base if graph is None else graph,
        adjustments,
        require_applied=require_applied,
    )


def test_missing_gain_is_added_to_exact_repeated_source_placement(assembly):
    snapshot, base = assembly
    adjustments = [_adjustment(snapshot)]
    originals = deepcopy((snapshot, base, adjustments))
    graph = _apply(assembly, adjustments)
    gain = _gain(graph, "audio-source-0001")
    assert gain == {
        "operationId": "source-mix-gain-audio-source-0001",
        "kind": "gain",
        "range": {"startSample": 0, "endSampleExclusive": 96000},
        "parameters": {"nodeId": "audio-source-0001", "gainDb": -6},
    }
    assert graph["nodes"] == base["nodes"]
    assert [op for op in graph["operations"] if op is not gain] == base["operations"]
    assert graph["operations"].index(gain) == 1
    assert (snapshot, base, adjustments) == originals
    graph["nodes"][0]["channelMap"].append(99)
    assert (snapshot, base, adjustments) == originals


def test_existing_microphone_gain_and_ceiling_are_relative_to_base(assembly):
    snapshot, base = assembly
    adjustment = _adjustment(
        snapshot, "microphone", gainDeltaDb=3, peakCeilingDeltaDb=3
    )
    graph = _apply(assembly, [adjustment])
    expected = deepcopy(base)
    _gain(expected, "audio-source-0002")["parameters"].update(
        gainDb=1, peakCeilingDbfs=-1.5
    )
    assert graph == expected
    assert _apply(assembly, [adjustment], graph=graph, require_applied=True) == expected


def test_two_windows_of_same_source_bind_distinct_nodes(assembly):
    snapshot, _ = assembly
    graph = _apply(
        assembly,
        [
            _adjustment(snapshot, gainDeltaDb=-4),
            _adjustment(snapshot, "game-repeat", gainDeltaDb=-8),
        ],
    )
    assert _gain(graph, "audio-source-0001")["parameters"]["gainDb"] == -4
    assert _gain(graph, "audio-source-0003")["parameters"]["gainDb"] == -8
    assert _gain(graph, "audio-source-0003")["range"]["startSample"] == 96000


def test_absent_adjustments_are_detached_noop_for_legacy_or_placed(assembly):
    _, graph = assembly
    assert validate_source_mix_adjustments({}, []) == []
    output = apply_source_mix_adjustments({}, {}, graph, [])
    assert output == graph and output is not graph
    output["nodes"].clear()
    assert graph["nodes"]


def test_validation_returns_detached_adjustments(assembly):
    snapshot, _ = assembly
    adjustments = [_adjustment(snapshot)]
    result = validate_source_mix_adjustments(snapshot, adjustments)
    assert result == adjustments and result is not adjustments
    result[0]["channels"].clear()
    assert adjustments[0]["channels"] == [0, 1]


@pytest.mark.parametrize(
    "field,value",
    [
        ("placementId", "unknown"),
        ("sourceId", "mic"),
        ("sourceSha256", "c" * 64),
        ("streamIndex", 1),
        ("channels", [1, 0]),
        ("streamIndex", True),
        ("channels", [False, 1]),
        ("channels", []),
        ("gainDeltaDb", True),
        ("gainDeltaDb", "3"),
        ("gainDeltaDb", float("nan")),
        ("gainDeltaDb", float("inf")),
        ("gainDeltaDb", -30.01),
        ("gainDeltaDb", 30.01),
        ("peakCeilingDeltaDb", False),
        ("peakCeilingDeltaDb", float("nan")),
        ("peakCeilingDeltaDb", 31),
        ("unexpected", "value"),
    ],
)
def test_invalid_adjustment_identity_and_numbers_rejected(assembly, field, value):
    snapshot, _ = assembly
    with pytest.raises(SourceMixError):
        validate_source_mix_adjustments(
            snapshot, [_adjustment(snapshot, **{field: value})]
        )


@pytest.mark.parametrize(
    "field",
    [
        "placementId",
        "sourceId",
        "sourceSha256",
        "streamIndex",
        "channels",
        "gainDeltaDb",
    ],
)
def test_required_adjustment_fields_rejected_when_missing(assembly, field):
    snapshot, _ = assembly
    adjustment = _adjustment(snapshot)
    del adjustment[field]
    with pytest.raises(SourceMixError):
        validate_source_mix_adjustments(snapshot, [adjustment])


@pytest.mark.parametrize("value", [None, {}, "adjustment", [None]])
def test_adjustments_require_an_array_of_records(assembly, value):
    with pytest.raises(SourceMixError):
        validate_source_mix_adjustments(assembly[0], value)


@pytest.mark.parametrize(
    "disabled", ["clip", "track", "clip-muted", "track-muted", "video"]
)
def test_inactive_and_non_audio_placements_cannot_be_adjusted(assembly, disabled):
    snapshot, _ = assembly
    adjustment = _adjustment(snapshot)
    placement = snapshot["layout"]["placements"][0]
    track = snapshot["layout"]["tracks"][0]
    if disabled == "clip":
        placement["enabled"] = False
    elif disabled == "track":
        track["enabled"] = False
    elif disabled == "clip-muted":
        placement["muted"] = True
    elif disabled == "track-muted":
        track["muted"] = True
    else:
        placement["mediaKind"] = "video"
    with pytest.raises(SourceMixError):
        validate_source_mix_adjustments(snapshot, [adjustment])


def test_duplicate_adjustments_rejected(assembly):
    adjustment = _adjustment(assembly[0])
    with pytest.raises(SourceMixError):
        _apply(assembly, [adjustment, deepcopy(adjustment)])


@pytest.mark.parametrize(
    "fault",
    [
        "missing-node",
        "missing-trim",
        "sha",
        "stream",
        "channels",
        "source-range",
        "output-range",
    ],
)
def test_base_target_must_bind_exact_cmap_identity_and_clocks(assembly, fault):
    snapshot, base = assembly
    adjustment = _adjustment(snapshot)
    node, trim = base["nodes"][1], base["operations"][0]
    if fault == "missing-node":
        base["nodes"].remove(node)
    elif fault == "missing-trim":
        base["operations"].remove(trim)
    elif fault in {"sha", "stream"}:
        trim["parameters"]["source"]["sha256" if fault == "sha" else "streamIndex"] = (
            "f" * 64 if fault == "sha" else 12
        )
    elif fault == "channels":
        node["channelMap"] = [1, 0]
    else:
        node["sourceRange" if fault == "source-range" else "outputRange"][
            "startSample"
        ] += 1
    with pytest.raises(SourceMixError):
        _apply(assembly, [adjustment])


@pytest.mark.parametrize(
    "fault",
    [
        "node",
        "trim",
        "gain-range",
        "other-gain-parameter",
        "missing-gain",
        "duplicate-gain",
        "duplicate-operation-id",
    ],
)
def test_actual_target_native_node_and_operations_must_match_base(assembly, fault):
    snapshot, base = assembly
    graph = deepcopy(base)
    gain = _gain(graph, "audio-source-0002")
    if fault == "node":
        graph["nodes"][2]["latencyCompensationSamples"] = 1
    elif fault == "trim":
        graph["operations"][1]["parameters"]["fadeInSamples"] = 48
    elif fault == "gain-range":
        gain["range"]["endSampleExclusive"] -= 1
    elif fault == "other-gain-parameter":
        gain["parameters"]["ceilingMode"] = "invented"
    elif fault == "missing-gain":
        graph["operations"].remove(gain)
    elif fault == "duplicate-gain":
        graph["operations"].append({**deepcopy(gain), "operationId": "other-gain"})
    else:
        graph["operations"].append(deepcopy(graph["operations"][0]))
    with pytest.raises(SourceMixError):
        _apply(assembly, [_adjustment(snapshot, "microphone")], graph=graph)


def test_compile_cannot_apply_the_same_delta_twice(assembly):
    adjustment = _adjustment(assembly[0])
    applied = _apply(assembly, [adjustment])
    with pytest.raises(SourceMixError):
        _apply(assembly, [adjustment], graph=applied)
    assert (
        _apply(assembly, [adjustment], graph=applied, require_applied=True) == applied
    )


@pytest.mark.parametrize(
    "fault", ["missing", "delta", "ceiling", "node", "trim", "extra-gain-param"]
)
def test_require_applied_detects_missing_or_tampered_application(assembly, fault):
    adjustment = _adjustment(
        assembly[0], "microphone", gainDeltaDb=3, peakCeilingDeltaDb=3
    )
    graph = _apply(assembly, [adjustment])
    gain = _gain(graph, "audio-source-0002")
    if fault == "missing":
        graph = deepcopy(assembly[1])
    elif fault == "delta":
        gain["parameters"]["gainDb"] += 0.1
    elif fault == "ceiling":
        gain["parameters"]["peakCeilingDbfs"] -= 0.1
    elif fault == "node":
        graph["nodes"][2]["channelMap"] = [0, 1]
    elif fault == "trim":
        graph["operations"][1]["parameters"]["fadeOutSamples"] = 1
    else:
        gain["parameters"]["unexpected"] = True
    with pytest.raises(SourceMixError):
        _apply(assembly, [adjustment], graph=graph, require_applied=True)


@pytest.mark.parametrize(
    "placement,extra",
    [
        ("game-first", {"peakCeilingDeltaDb": 0}),
        ("microphone", {"gainDeltaDb": 30, "peakCeilingDeltaDb": 5}),
        ("microphone", {"gainDeltaDb": 30, "peakCeilingDeltaDb": 4.5}),
    ],
)
def test_ceiling_adjustment_requires_existing_ceiling_and_negative_result(
    assembly, placement, extra
):
    with pytest.raises(SourceMixError):
        _apply(assembly, [_adjustment(assembly[0], placement, **extra)])


def test_overlapping_identity_mapping_is_not_resolved_by_native_ordinal(assembly):
    snapshot, base = assembly
    snapshot["layout"]["placements"][2].update(
        start=deepcopy(snapshot["layout"]["placements"][0]["start"]),
        end=deepcopy(snapshot["layout"]["placements"][0]["end"]),
    )
    base["nodes"][3]["outputRange"] = deepcopy(base["nodes"][1]["outputRange"])
    base["operations"][3]["range"] = deepcopy(base["nodes"][1]["outputRange"])
    with pytest.raises(SourceMixError):
        _apply(assembly, [_adjustment(snapshot)])


def test_sound_effect_nodes_operations_and_metadata_are_untouched(assembly):
    snapshot, base = assembly
    graph = deepcopy(base)
    node = {**deepcopy(base["nodes"][1]), "nodeId": "sound-effect-boom"}
    trim = deepcopy(base["operations"][0])
    trim.update(operationId="sound-effect-trim")
    trim["parameters"].update(nodeId=node["nodeId"], sourceId="sfx-boom")
    graph["nodes"].append(node)
    graph["operations"].append(trim)
    graph["metadata"] = {"events": [{"eventId": "boom", "startFrame": 61}]}
    original = deepcopy(graph)
    adjustment = _adjustment(snapshot, "microphone", gainDeltaDb=2)
    result = _apply(assembly, [adjustment], graph=graph)
    expected = deepcopy(original)
    _gain(expected, "audio-source-0002")["parameters"]["gainDb"] = 0
    assert result == expected and graph == original
    assert _apply(assembly, [adjustment], graph=result, require_applied=True) == result


def test_resampled_placement_uses_native_source_clock_and_preserves_resampling(
    assembly,
):
    snapshot, _ = assembly
    item = snapshot["layout"]["placements"][0]
    item["routing"]["audioSelection"]["sourceSampleRate"] = 44100
    item["in"] = _time(44100, "game", den=44100)
    item["out"] = _time(132300, "game", den=44100)
    base = _audio(
        snapshot,
        {item["sourceId"]: item for item in snapshot["sources"]},
        {item["trackId"]: item for item in snapshot["layout"]["tracks"]},
        SimpleNamespace(raw_dir="."),
        192000,
        None,
    )
    adjustment = _adjustment(snapshot)
    result = _apply((snapshot, base), [adjustment])
    assert result["operations"][1] == base["operations"][1]
    assert result["operations"][1]["kind"] == "resample"
    assert result["operations"][2]["kind"] == "gain"
    changed = deepcopy(result)
    changed["operations"][1]["parameters"]["sourceSampleRate"] = 48000
    with pytest.raises(SourceMixError):
        _apply((snapshot, base), [adjustment], graph=changed, require_applied=True)


@pytest.mark.parametrize(
    "fault", ["channel-bool", "gain-bool", "clock-bool", "bad-kind", "bad-node-ref"]
)
def test_graph_scalar_types_cannot_masquerade_as_canonical_numbers(assembly, fault):
    snapshot, base = assembly
    adjustment = _adjustment(snapshot, "microphone", gainDeltaDb=3)
    applied = _apply(assembly, [adjustment])
    if fault == "channel-bool":
        applied["nodes"][2]["channelMap"] = [False, False]
    elif fault == "gain-bool":
        _gain(applied, "audio-source-0002")["parameters"]["gainDb"] = True
    elif fault == "clock-bool":
        applied["nodes"][2]["outputRange"]["startSample"] = False
    elif fault == "bad-kind":
        del applied["operations"][1]["kind"]
    else:
        applied["operations"][1]["parameters"]["nodeId"] = []
    with pytest.raises(SourceMixError):
        _apply(assembly, [adjustment], graph=applied, require_applied=True)
    assert base["nodes"][2]["channelMap"] == [0, 0]


@pytest.mark.parametrize("fault", ["extra-trim", "extra-filter"])
def test_base_target_cannot_contain_duplicate_or_unknown_native_filters(
    assembly, fault
):
    snapshot, base = assembly
    added = deepcopy(base["operations"][0])
    added["operationId"] = "unrelated-id"
    if fault == "extra-filter":
        added["kind"] = "invented-filter"
    else:
        added["parameters"]["sourceId"] = "other-source"
    base["operations"].insert(1, added)
    with pytest.raises(SourceMixError):
        _apply(assembly, [_adjustment(snapshot)])


@pytest.mark.parametrize("gain,delta", [(30, 1), (-120, -1)])
def test_result_gain_bounds_are_enforced(assembly, gain, delta):
    snapshot, base = assembly
    snapshot["layout"]["placements"][1]["gainDb"] = gain
    _gain(base, "audio-source-0002")["parameters"]["gainDb"] = gain
    with pytest.raises(SourceMixError):
        _apply(assembly, [_adjustment(snapshot, "microphone", gainDeltaDb=delta)])


def test_created_gain_id_cannot_collide_with_a_sound_effect_operation(assembly):
    snapshot, base = assembly
    graph = deepcopy(base)
    graph["operations"].append(
        {
            "operationId": "source-mix-gain-audio-source-0001",
            "kind": "mix",
            "parameters": {},
        }
    )
    with pytest.raises(SourceMixError):
        _apply(assembly, [_adjustment(snapshot)], graph=graph)


@pytest.mark.parametrize("ceiling", [-12, -1])
def test_ceiling_native_inclusive_boundaries_are_valid(assembly, ceiling):
    adjustment = _adjustment(
        assembly[0],
        "microphone",
        gainDeltaDb=0,
        peakCeilingDeltaDb=ceiling + 4.5,
    )
    result = _apply(assembly, [adjustment])
    assert (
        _gain(result, "audio-source-0002")["parameters"]["peakCeilingDbfs"] == ceiling
    )


@pytest.mark.parametrize("ceiling", [-12.01, -0.99])
def test_ceiling_outside_native_dsp_range_is_rejected(assembly, ceiling):
    adjustment = _adjustment(
        assembly[0],
        "microphone",
        gainDeltaDb=0,
        peakCeilingDeltaDb=ceiling + 4.5,
    )
    with pytest.raises(SourceMixError):
        _apply(assembly, [adjustment])


@pytest.mark.parametrize("require_applied", [False, True])
def test_shadow_source_contribution_with_fresh_ids_is_rejected(
    assembly, require_applied
):
    snapshot, base = assembly
    adjustment = _adjustment(snapshot)
    graph = _apply(assembly, [adjustment]) if require_applied else deepcopy(base)
    shadow = deepcopy(base["nodes"][1])
    shadow["nodeId"] = "fresh-shadow-source"
    shadow_trim = deepcopy(base["operations"][0])
    shadow_trim["operationId"] = "fresh-shadow-trim"
    shadow_trim["parameters"]["nodeId"] = shadow["nodeId"]
    graph["nodes"].append(shadow)
    graph["operations"].append(shadow_trim)
    original = deepcopy(graph)
    with pytest.raises(SourceMixError):
        _apply(assembly, [adjustment], graph=graph, require_applied=require_applied)
    assert graph == original
