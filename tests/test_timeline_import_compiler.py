"""Placed source assembly contracts; these unit fixtures make no media approvals."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.timeline.event_clock import sample_rate_boundary
from avo.timeline.initial_cut import initial_cut_proof_request
from tests.test_timeline_import_layout import placed_snapshot, raw_time


def _request(tmp_path, snapshot):
    before = deepcopy(snapshot)
    workspace = SimpleNamespace(
        raw_dir=tmp_path,
        require_active=lambda name: {"headRevisionId": "placed-canonical"},
        store=lambda name: SimpleNamespace(
            revision=lambda revision_id: {"snapshot": deepcopy(snapshot)}
        ),
    )
    request = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-placed",
        output=tmp_path / "proof.mp4",
        frame_rate=snapshot["layout"]["programClock"]["frameRate"],
        width=128,
        height=96,
        sample_rate=48000,
    )
    assert snapshot == before
    return request


def _source(snapshot, tmp_path, source_id, digest):
    source = {
        "sourceId": source_id,
        "kind": "raw",
        "locator": str(tmp_path / f"{source_id}.mkv"),
        "fingerprint": {"sha256": digest * 64, "sizeBytes": 1},
    }
    snapshot["sources"].append(source)
    return source


def _picture_snapshot(tmp_path):
    snapshot = placed_snapshot()
    snapshot["sources"][0].update(
        locator=str(tmp_path / "camera.mkv"),
        streamMetadata={
            "videoStreamIndex": 0,
            "audioSelection": {
                "streamIndex": 1,
                "channels": [0, 1],
                "sourceLayout": "stereo",
                "outputLayout": "stereo",
                "sourceSampleRate": 48000,
            },
        },
    )
    return snapshot


def _layout_operation(request):
    operations = request["videoGraph"]["operations"]
    assert len(operations) == 1
    operation = operations[0]
    assert operation["kind"] == "source-layout"
    return operation


def _audio_placement(
    snapshot,
    placement_id,
    track_id,
    source_id,
    *,
    start,
    end,
    raw_start=0,
    native_rate=48000,
    channel_map=(0, 1),
    **state,
):
    snapshot["layout"]["tracks"].append(
        {
            "trackId": track_id,
            "kind": "audio",
            "order": len(snapshot["layout"]["tracks"]),
            "enabled": state.pop("track_enabled", True),
            "muted": state.pop("track_muted", False),
            "evidenceOrigin": "export",
        }
    )
    raw_length = (end - start) * native_rate // 48000
    placement = {
        "placementId": placement_id,
        "elementId": f"/tracks/{track_id}/children/{placement_id}",
        "trackId": track_id,
        "sourceId": source_id,
        "mediaKind": "audio",
        "in": raw_time(raw_start, source_id, den=native_rate),
        "out": raw_time(raw_start + raw_length, source_id, den=native_rate),
        "start": {
            "ticks": start,
            "timebase": {"num": 1, "den": 48000},
            "domain": "cmap-output",
        },
        "end": {
            "ticks": end,
            "timebase": {"num": 1, "den": 48000},
            "domain": "cmap-output",
        },
        "enabled": True,
        "routing": {
            "audioSelection": {
                "streamIndex": 2,
                "channels": list(channel_map),
                "sourceLayout": "stereo",
                "outputLayout": "dual-mono" if len(channel_map) == 1 else "stereo",
                "sourceSampleRate": native_rate,
            }
        },
        "evidenceOrigin": "export",
        **state,
    }
    snapshot["layout"]["placements"].append(placement)
    return placement


def _audio_sources(request):
    graph = request["audioGraph"]
    nodes = {node["nodeId"]: node for node in graph["nodes"]}
    trims = [op for op in graph["operations"] if op["kind"] == "trim"]
    return {
        op["parameters"]["sourceId"]: (nodes[op["parameters"]["nodeId"]], op)
        for op in trims
    }


def test_placed_picture_keeps_every_region_raw_trim_layer_and_black_gap(tmp_path):
    snapshot = _picture_snapshot(tmp_path)
    repeat = snapshot["layout"]["placements"][1]
    repeat["in"], repeat["out"] = raw_time(48), raw_time(72)

    request = _request(tmp_path, snapshot)
    operation = _layout_operation(request)
    assert operation["inputs"] == ["camera"]
    assert operation["outputRange"] == {"startFrame": 0, "endFrameExclusive": 96}
    assert operation["parameters"]["background"] == "black"
    placements = {p["placementId"]: p for p in operation["parameters"]["placements"]}
    assert set(placements) == {"first", "repeat", "upper"}
    for original in snapshot["layout"]["placements"]:
        compiled = placements[original["placementId"]]
        assert compiled["sourceId"] == "camera"
        assert compiled["trackId"] == original["trackId"]
        assert compiled["mediaKind"] == "video"
        assert compiled["enabled"] is True
        assert compiled["zOrder"] == (0 if original["trackId"] == "v1" else 1)
        assert compiled["sourceRange"] == {
            "startTicks": original["in"]["ticks"],
            "endTicks": original["out"]["ticks"],
            "timebase": {"num": 1, "den": 24},
        }
        assert compiled["outputRange"] == {
            "startFrame": original["start"]["ticks"],
            "endFrameExclusive": original["end"]["ticks"],
        }
        assert compiled["source"] == {
            "locator": str(tmp_path / "camera.mkv"),
            "sha256": "a" * 64,
            "mediaClass": "source",
            "ancestry": [],
            "streamIndex": 0,
        }
    assert request["sourceFingerprints"] == {"camera": "a" * 64}


def test_placed_still_holds_original_without_turning_it_into_a_generated_clip(tmp_path):
    snapshot = _picture_snapshot(tmp_path)
    _source(snapshot, tmp_path, "still", "e")
    still = snapshot["layout"]["placements"][2]
    still.update(sourceId="still", mediaKind="still")
    still["in"], still["out"] = raw_time(0, "still"), raw_time(1, "still")

    request = _request(tmp_path, snapshot)
    operation = _layout_operation(request)
    compiled = next(
        p for p in operation["parameters"]["placements"] if p["placementId"] == "upper"
    )
    assert set(operation["inputs"]) == {"camera", "still"}
    assert compiled["mediaKind"] == "still"
    assert compiled["sourceRange"] == {
        "startTicks": 0,
        "endTicks": 1,
        "timebase": {"num": 1, "den": 24},
    }
    assert compiled["outputRange"] == {"startFrame": 30, "endFrameExclusive": 42}
    assert compiled["source"]["sha256"] == "e" * 64
    assert request["sourceFingerprints"]["still"] == "e" * 64


@pytest.mark.parametrize("disabled_owner", ["placement", "track"])
def test_disabled_picture_stays_in_source_accounting(tmp_path, disabled_owner):
    snapshot = _picture_snapshot(tmp_path)
    if disabled_owner == "placement":
        snapshot["layout"]["placements"][2]["enabled"] = False
    else:
        snapshot["layout"]["tracks"][1]["enabled"] = False

    request = _request(tmp_path, snapshot)
    placements = _layout_operation(request)["parameters"]["placements"]
    assert len(placements) == 3
    assert (
        next(p for p in placements if p["placementId"] == "upper")["enabled"] is False
    )
    assert request["sourceFingerprints"] == {"camera": "a" * 64}


def test_independent_audio_preserves_sample_positions_channels_gain_and_silence(
    tmp_path,
):
    snapshot = _picture_snapshot(tmp_path)
    _source(snapshot, tmp_path, "mic", "1")
    _source(snapshot, tmp_path, "recorder", "2")
    _audio_placement(
        snapshot,
        "dialogue",
        "a1",
        "mic",
        start=24001,
        end=72001,
        raw_start=12001,
        channel_map=(1,),
        gainDb=-3.0,
    )
    _audio_placement(
        snapshot,
        "separate",
        "a2",
        "recorder",
        start=480,
        end=48480,
        raw_start=441,
        native_rate=44100,
    )

    request = _request(tmp_path, snapshot)
    sources = _audio_sources(request)
    assert set(sources) == {"mic", "recorder"}, (
        "muxed picture audio must not double explicit tracks"
    )
    mic, _ = sources["mic"]
    recorder, _ = sources["recorder"]
    assert mic["kind"] == recorder["kind"] == "source"
    assert mic["sourceRange"] == {"startSample": 12001, "endSampleExclusive": 60001}
    assert mic["outputRange"] == {"startSample": 24001, "endSampleExclusive": 72001}
    assert mic["channelMap"] == [1, 1]
    assert recorder["sourceSampleRate"] == 44100
    assert recorder["sourceRange"] == {"startSample": 441, "endSampleExclusive": 44541}
    assert recorder["outputRange"] == {"startSample": 480, "endSampleExclusive": 48480}
    assert recorder["channelMap"] == [0, 1]
    for source_id, (_, trim) in sources.items():
        assert (
            trim["parameters"]["source"]["sha256"]
            == request["sourceFingerprints"][source_id]
        )
        assert trim["parameters"]["source"]["streamIndex"] == 2
        assert trim["parameters"].get("fadeInSamples", 0) == 0
        assert trim["parameters"].get("fadeOutSamples", 0) == 0
        assert "dialogueNoiseReductionPolicy" not in trim["parameters"]
        assert "dialogueTreatmentPolicy" not in trim["parameters"]
    operations = request["audioGraph"]["operations"]
    gains = [op for op in operations if op["kind"] == "gain"]
    assert len(gains) == 1
    assert gains[0]["parameters"] == {"nodeId": mic["nodeId"], "gainDb": -3.0}
    assert gains[0]["range"] == mic["outputRange"]
    resamples = [op for op in operations if op["kind"] == "resample"]
    assert len(resamples) == 1
    assert resamples[0]["parameters"] == {
        "nodeId": recorder["nodeId"],
        "sourceSampleRate": 44100,
        "targetSampleRate": 48000,
    }
    assert resamples[0]["range"] == recorder["outputRange"]
    assert any(
        op["kind"] == "mix"
        and op["range"]["startSample"] <= 24001
        and op["range"]["endSampleExclusive"] >= 48480
        for op in operations
    )
    silence = [
        n["outputRange"]
        for n in request["audioGraph"]["nodes"]
        if n["kind"] == "silence"
    ]
    for first, last in ((0, 480), (72001, 192000)):
        assert any(
            r["startSample"] <= first and r["endSampleExclusive"] >= last
            for r in silence
        )
    encodes = [op for op in operations if op["kind"] == "encode"]
    assert len(encodes) == 1
    assert encodes[0]["range"] == {"startSample": 0, "endSampleExclusive": 192000}
    assert request["audioGraph"]["singleFinalEncode"] is True


@pytest.mark.parametrize(
    "state",
    [
        {"muted": True},
        {"enabled": False},
        {"track_muted": True},
        {"track_enabled": False},
    ],
)
def test_muted_or_disabled_audio_is_inaudible_but_keeps_original_fingerprint(
    tmp_path, state
):
    snapshot = _picture_snapshot(tmp_path)
    _source(snapshot, tmp_path, "muted", "3")
    _audio_placement(snapshot, "muted", "a1", "muted", start=0, end=48000, **state)

    request = _request(tmp_path, snapshot)
    assert _audio_sources(request) == {}
    assert request["sourceFingerprints"] == {"camera": "a" * 64, "muted": "3" * 64}
    assert request["audioGraph"]["nodes"]
    assert all(node["kind"] == "silence" for node in request["audioGraph"]["nodes"])


def test_fractional_program_clock_uses_absolute_half_up_sample_boundaries(tmp_path):
    snapshot = _picture_snapshot(tmp_path)
    clock = snapshot["layout"]["programClock"]
    clock["frameRate"] = {"num": 30000, "den": 1001}
    clock["timebase"] = {"num": 1001, "den": 30000}
    snapshot["importOutput"]["frameRate"] = deepcopy(clock["frameRate"])
    for item in snapshot["layout"]["placements"]:
        for key in ("in", "out", "start", "end"):
            item[key]["timebase"] = deepcopy(clock["timebase"])
    for gap in snapshot["layout"]["gaps"]:
        for key in ("start", "end"):
            gap[key]["timebase"] = deepcopy(clock["timebase"])
    snapshot["layout"]["duration"]["timebase"] = deepcopy(clock["timebase"])
    _source(snapshot, tmp_path, "mic", "1")
    audio = _audio_placement(snapshot, "half-sample", "a1", "mic", start=0, end=48000)
    audio["start"].update(ticks=1, timebase={"num": 1, "den": 96000})
    audio["end"].update(ticks=96001, timebase={"num": 1, "den": 96000})

    request = _request(tmp_path, snapshot)
    node, _ = _audio_sources(request)["mic"]
    assert node["outputRange"] == {"startSample": 1, "endSampleExclusive": 48001}
    assert node["sourceRange"] == {"startSample": 0, "endSampleExclusive": 48000}
    encode = next(
        op for op in request["audioGraph"]["operations"] if op["kind"] == "encode"
    )
    assert encode["range"]["endSampleExclusive"] == sample_rate_boundary(
        96 * 1001, source_rate=30000, target_rate=48000
    )
    assert _layout_operation(request)["outputRange"] == {
        "startFrame": 0,
        "endFrameExclusive": 96,
    }


def test_repeated_audio_occurrences_keep_distinct_source_nodes(tmp_path):
    snapshot = _picture_snapshot(tmp_path)
    _source(snapshot, tmp_path, "mic", "1")
    _audio_placement(snapshot, "first-audio", "a1", "mic", start=1, end=48001)
    _audio_placement(snapshot, "repeat-audio", "a2", "mic", start=96001, end=144001)

    request = _request(tmp_path, snapshot)
    nodes = [
        node for node in request["audioGraph"]["nodes"] if node["kind"] == "source"
    ]
    assert len(nodes) == 2
    assert len({node["nodeId"] for node in nodes}) == 2
    assert [node["outputRange"] for node in nodes] == [
        {"startSample": 1, "endSampleExclusive": 48001},
        {"startSample": 96001, "endSampleExclusive": 144001},
    ]
    assert (
        nodes[0]["sourceRange"]
        == nodes[1]["sourceRange"]
        == {
            "startSample": 0,
            "endSampleExclusive": 48000,
        }
    )
    trims = [op for op in request["audioGraph"]["operations"] if op["kind"] == "trim"]
    assert len(trims) == 2
    assert {trim["parameters"]["sourceId"] for trim in trims} == {"mic"}


def test_placed_compiler_rejects_unavailable_output_sample_rate(tmp_path):
    snapshot = _picture_snapshot(tmp_path)
    snapshot["layout"]["programClock"]["audioSampleRate"] = 44100
    snapshot["importOutput"]["audioSampleRate"] = 44100
    with pytest.raises(ValueError, match="48000 Hz"):
        _request(tmp_path, snapshot)


def test_placed_audio_rejects_endpoint_rounding_that_changes_pcm_length(tmp_path):
    snapshot = _picture_snapshot(tmp_path)
    _source(snapshot, tmp_path, "mic", "1")
    audio = _audio_placement(snapshot, "short", "a1", "mic", start=0, end=1)
    audio["in"].update(ticks=1, timebase={"num": 1, "den": 96000})
    audio["out"].update(ticks=2, timebase={"num": 1, "den": 96000})
    audio["end"].update(ticks=1, timebase={"num": 1, "den": 96000})
    with pytest.raises(ValueError, match="native PCM sample counts"):
        _request(tmp_path, snapshot)
