"""Placement admission uses explicit streams and never duplicates muxed audio."""

import json
from copy import deepcopy

import pytest

import test_timeline_import_service as import_fixtures
from avo.adapters.media.ffprobe import FfprobeMediaAdapter
from avo.adapters.media.otio_reader import read_otio
from avo.adapters.media.still_probe import verify_literal_still
from avo.timeline.import_service import TimelineImportService
from test_timeline_import_service import (
    FIXTURE,
    _approve_fixture_sync,
    _probe,
)

placed_project = pytest.fixture(name="import_project")(
    import_fixtures.import_project.__wrapped__
)


@pytest.mark.parametrize("mode", [None, "declared-treatments"])
def test_picture_treatments_require_distinct_admission_mode(
    import_project, tmp_path, mode
):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    export = tmp_path / "treatments.otio"
    first = _prepare(service, export, original)
    options = deepcopy(first["session"]["options"])
    mapping = options["mappings"]["/tracks/children/0/children/1/media_reference"]
    mapping["pictureTransform"] = {
        "canvasWidth": 640,
        "canvasHeight": 360,
        "x": 10,
        "y": 20,
        "width": 320,
        "height": 180,
    }
    mapping["pictureFade"] = {"inFrames": 0, "outFrames": 6}
    if mode:
        options["declarations"].update(reconstructionMode=mode, sourceOnly=False)
    prepared = service.prepare(
        export,
        mappings=options["mappings"],
        declarations=options["declarations"],
        actor="fixture",
        reason="Explicit treatments",
    )
    result = service.validate(prepared["importId"])
    if mode is None:
        assert result["status"] == "blocked"
        return
    assert result["status"] == "awaiting-sync", result.get("findings")
    item = result["proposal"]["snapshot"]["layout"]["placements"][0]
    assert item["pictureTransform"] == mapping["pictureTransform"]
    assert item["pictureFade"] == mapping["pictureFade"]
    _approve_fixture_sync(service, result["proposal"])
    ready = service.validate(prepared["importId"])
    selected = service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Synthetic treated activation",
    )
    assert (
        selected["revision"]["snapshot"]["originRef"]["capabilityVersion"]
        == "placed-treatments-1.0.0"
    )
    from avo.timeline.import_evidence import verify_import_origin

    assert verify_import_origin(service.workspace, selected["revision"])


@pytest.mark.parametrize("declared", [False, True])
def test_repetition_admission_is_explicit_and_keeps_native_clock(
    import_project, tmp_path, declared
):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    export = tmp_path / "sampling.otio"
    first = _prepare(service, export, original)
    options = deepcopy(first["session"]["options"])
    options["declarations"]["output"]["frameRate"] = {"num": 48, "den": 1}
    reference = "/tracks/children/0/children/1/media_reference"
    if declared:
        options["mappings"][reference]["pictureSampling"] = "repeat-2x"
    prepared = service.prepare(
        export,
        mappings=options["mappings"],
        declarations=options["declarations"],
        actor="fixture",
        reason="Explicit sampling admission",
    )
    result = service.validate(prepared["importId"])
    if not declared:
        assert result["status"] == "blocked"
        return
    assert result["status"] == "awaiting-sync", result.get("findings")
    snapshot = result["proposal"]["snapshot"]
    item = snapshot["layout"]["placements"][0]
    assert item["pictureSampling"] == "repeat-2x"
    from avo.timeline.mapping import cmap_output_to_raw

    start = item["start"]["ticks"]
    assert cmap_output_to_raw(
        snapshot, start + 1, placement_id=item["placementId"]
    ) == (item["sourceId"], 0)
    source = next(s for s in snapshot["sources"] if s["sourceId"] == item["sourceId"])
    assert source["streamMetadata"]["videoClock"]["frameRate"] == {"num": 24, "den": 1}
    _approve_fixture_sync(service, result["proposal"])
    ready = service.validate(prepared["importId"])
    selected = service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Synthetic sampling activation",
    )
    assert (
        selected["revision"]["snapshot"]["originRef"]["capabilityVersion"]
        == "placed-sampling-1.0.0"
    )
    from avo.timeline.import_evidence import verify_import_origin

    assert verify_import_origin(service.workspace, selected["revision"])


@pytest.mark.parametrize("declared", [None, 5504, 5505])
def test_audio_tail_requires_exact_declared_decoded_sample_gap(
    import_project, tmp_path, declared
):
    project, provider, original = import_project

    def probe(paths):
        result = _probe(paths)
        result["sources"][0]["streams"]["audio"][0]["durationSeconds"] = 90496 / 48000
        result["sources"][0]["streams"]["audio"][0]["durationTicks"] = 90496
        return result

    def count(path, stream, *, expected_sha256):
        return {
            "status": "verified",
            "sourceSha256": expected_sha256,
            "streamIndex": stream,
            "sampleCount": 90496,
            "method": "fixture-decoded-samples",
        }

    service = TimelineImportService(
        project,
        provider_root=provider,
        reader=read_otio,
        probe=probe,
        audio_clock_probe=count,
    )
    export = tmp_path / "audio-tail.otio"
    first = _prepare(service, export, original)
    options = deepcopy(first["session"]["options"])
    if declared is not None:
        options["mappings"]["/tracks/children/1/children/0/media_reference"][
            "audioTailSilenceSamples"
        ] = declared
    prepared = service.prepare(
        export,
        mappings=options["mappings"],
        declarations=options["declarations"],
        actor="fixture",
        reason="Explicit audio endpoint",
    )
    result = service.validate(prepared["importId"])
    if declared != 5504:
        assert result["status"] == "blocked"
        return
    assert result["status"] == "awaiting-sync", result.get("findings")
    item = result["proposal"]["snapshot"]["layout"]["placements"][1]
    assert item["audioTailSilenceSamples"] == 5504
    assert (
        item["out"]["ticks"]
        * item["out"]["timebase"]["num"]
        / item["out"]["timebase"]["den"]
        == 90496 / 48000
    )


def _prepare(service, path, original):
    raw = json.loads(FIXTURE.read_text())
    track = raw["tracks"]["children"][0]
    clip = deepcopy(track["children"][0])
    track["children"] = [
        {"OTIO_SCHEMA": "Gap.1", "source_range": deepcopy(clip["source_range"])},
        clip,
    ]
    audio = deepcopy(track)
    audio["kind"] = "Audio"
    audio["children"] = [deepcopy(clip)]
    raw["tracks"]["children"].append(audio)
    path.write_text(json.dumps(raw))
    refs = [
        "/tracks/children/0/children/1/media_reference",
        "/tracks/children/1/children/0/media_reference",
    ]
    maps = {ref: {"path": str(original), "identityConfirmed": True} for ref in refs}
    maps[refs[0]]["videoStreamIndex"] = 0
    maps[refs[1]]["audioSelection"] = {
        "streamIndex": 1,
        "channels": [0, 1],
        "sourceLayout": "stereo",
        "outputLayout": "stereo",
    }
    return service.prepare(
        path,
        mappings=maps,
        declarations={
            "sourceOnly": True,
            "layoutMode": "placed",
            "output": {
                "width": 640,
                "height": 360,
                "frameRate": {"num": 24, "den": 1},
                "audioSampleRate": 48000,
                "channelLayout": "stereo",
            },
        },
        actor="fixture",
        reason="Placement test",
    )


def test_placed_service_keeps_program_extent_tracks_and_independent_routing(
    import_project,
    tmp_path,
):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = _prepare(service, tmp_path / "placed.otio", original)
    result = service.validate(prepared["importId"])
    assert result["status"] == "awaiting-sync", result.get("findings")
    snapshot = result["proposal"]["snapshot"]
    assert snapshot["layoutMode"] == "placed"
    assert "segments" not in snapshot
    layout = snapshot["layout"]
    assert layout["duration"]["ticks"] == 96
    assert len(layout["gaps"]) == 1
    assert [p["mediaKind"] for p in layout["placements"]] == ["video", "audio"]
    assert layout["placements"][0]["start"]["ticks"] == 48
    assert "audioSelection" not in layout["placements"][0]["routing"]
    _approve_fixture_sync(service, result["proposal"])
    ready = service.validate(prepared["importId"])
    activated = service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Select placed fixture",
    )
    assert activated["revision"]["snapshot"]["layout"] == layout


@pytest.mark.parametrize("defect", ["raw-quarter-frame", "program-half-frame"])
def test_invalid_picture_clock_blocks_before_activation_journal(
    import_project, tmp_path, defect
):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    path = tmp_path / "invalid.otio"
    first = _prepare(service, path, original)
    raw = json.loads(path.read_text())
    clip = raw["tracks"]["children"][0]["children"][1]
    if defect == "raw-quarter-frame":
        clip["source_range"]["start_time"]["value"] = 240.25
    else:
        clip["source_range"]["duration"]["value"] = 47.5
    path.write_text(json.dumps(raw))
    prepared = service.prepare(
        path,
        mappings=first["session"]["options"]["mappings"],
        declarations=first["session"]["options"]["declarations"],
        actor="fixture",
        reason="Invalid clocks",
    )
    result = service.validate(prepared["importId"])
    assert result["status"] == "blocked"
    assert not service._pending_path().exists()
    assert not service.workspace.artifact_path("cmap").exists()


def test_declared_audio_gain_and_mute_are_explicit_packet_options(
    import_project, tmp_path
):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    path = tmp_path / "states.otio"
    first = _prepare(service, path, original)
    options = deepcopy(first["session"]["options"])
    audio = options["mappings"]["/tracks/children/1/children/0/media_reference"]
    audio.update(gainDb=-3, muted=True)
    prepared = service.prepare(
        path,
        mappings=options["mappings"],
        declarations=options["declarations"],
        actor="fixture",
        reason="Declare explicit audio state",
    )
    result = service.validate(prepared["importId"])
    placement = result["proposal"]["snapshot"]["layout"]["placements"][1]
    assert placement["gainDb"] == -3
    assert placement["muted"] is True
    assert placement["evidenceOrigin"] == "editor-declaration"
    assert prepared["importId"] != first["importId"]


def test_literal_still_virtual_trim_is_a_verified_first_frame_hold(
    import_project, tmp_path
):
    from PIL import Image

    project, provider, original = import_project
    image = original.with_name("literal-%04d.png")
    Image.new("RGB", (128, 96), "red").save(image)
    raw = json.loads(FIXTURE.read_text())
    raw["tracks"]["children"][0]["children"][0]["source_range"]["start_time"][
        "value"
    ] = 252
    path = tmp_path / "still.otio"
    path.write_text(json.dumps(raw))
    service = TimelineImportService(
        project,
        provider_root=provider,
        reader=read_otio,
        probe=FfprobeMediaAdapter().inventory,
        still_probe=verify_literal_still,
    )
    prepared = service.prepare(
        path,
        mappings={
            "/tracks/children/0/children/0/media_reference": {
                "path": str(image),
                "identityConfirmed": True,
                "videoStreamIndex": 0,
                "mediaKind": "still",
            }
        },
        declarations={
            "sourceOnly": True,
            "layoutMode": "placed",
            "output": {
                "width": 640,
                "height": 360,
                "frameRate": {"num": 24, "den": 1},
                "audioSampleRate": 48000,
                "channelLayout": "stereo",
            },
        },
        actor="fixture",
        reason="Verify static hold",
    )
    result = service.validate(prepared["importId"])
    assert result["status"] == "awaiting-sync", result
    item = result["proposal"]["snapshot"]["layout"]["placements"][0]
    assert item["mediaKind"] == "still"
    assert item["in"]["ticks"] == 0
    assert item["out"]["ticks"] == 1
    assert item["out"]["timebase"] == {"num": 1, "den": 24}
    assert item["end"]["ticks"] == 48


def test_non_square_pixel_picture_blocks_instead_of_distorting(
    import_project, tmp_path
):
    project, provider, original = import_project

    def probe(paths):
        result = _probe(paths)
        result["sources"][0]["streams"]["video"][0]["sampleAspectRatio"] = "2:1"
        return result

    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=probe
    )
    prepared = _prepare(service, tmp_path / "anamorphic.otio", original)
    result = service.validate(prepared["importId"])
    assert result["status"] == "blocked"
    assert any("square" in finding["message"] for finding in result["findings"])
