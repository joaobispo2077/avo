"""Generated references require explicit authorial data and pinned fonts."""

import json

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import TimelineImportService
from tests import test_timeline_import_service as fixtures

project_fixture = pytest.fixture(name="import_project")(
    fixtures.import_project.__wrapped__
)


def test_generated_title_admits_only_explicit_authorial_and_font_inputs(
    import_project, tmp_path
):
    project, provider, _ = import_project
    document = tmp_path / "original-title.json"
    document.write_text('{"text":"2026"}')
    font = tmp_path / "font.ttf"
    font.write_bytes(b"\x00\x01\x00\x00fixture-font")
    raw = json.loads(fixtures.FIXTURE.read_text())
    clip = raw["tracks"]["children"][0]["children"][0]
    clip["media_reference"] = {"OTIO_SCHEMA": "MissingReference.1"}
    clip["source_range"]["start_time"]["value"] = 0
    export = tmp_path / "title.otio"
    export.write_text(json.dumps(raw))
    reference = "/tracks/children/0/children/0/media_reference"
    title = {
        "text": "2026",
        "canvasWidth": 640,
        "canvasHeight": 360,
        "x": 320,
        "y": 180,
        "fontSize": 64,
        "color": "#FFFFFFFF",
        "anchor": "center",
    }

    def no_media_probe(paths):
        raise AssertionError("Authorial input must not be probed as audiovisual media")

    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=no_media_probe
    )
    prepared = service.prepare(
        export,
        mappings={
            reference: {
                "path": str(document),
                "identityConfirmed": True,
                "mediaKind": "title",
                "title": title,
                "font": {"path": str(font), "fingerprint": file_fingerprint(font)},
            }
        },
        declarations={
            "sourceOnly": False,
            "reconstructionMode": "declared-treatments",
            "layoutMode": "placed",
            "generatedTitles": [reference],
            "mediaOrigins": {reference: {"value": "0", "rate": "24"}},
            "output": {
                "width": 640,
                "height": 360,
                "frameRate": {"num": 24, "den": 1},
                "audioSampleRate": 48000,
                "channelLayout": "stereo",
            },
        },
        actor="fixture",
        reason="Explicit authorial title",
    )
    result = service.validate(prepared["importId"])
    assert result["status"] == "awaiting-sync", result.get("findings")
    snapshot = result["proposal"]["snapshot"]
    from avo.timeline.lineage import validate_cmap_snapshot

    selected = service._selected_snapshot(
        result["session"], result["proposal"], {"operationId": "a" * 64}
    )
    validate_cmap_snapshot(selected)
    item = snapshot["layout"]["placements"][0]
    assert item["mediaKind"] == "title" and item["title"] == title
    assert {s["kind"] for s in snapshot["sources"]} == {"authorial"}
    assert item["fontSourceId"] in {s["sourceId"] for s in snapshot["sources"]}
    from avo.timeline.mapping import cmap_output_to_raw

    assert cmap_output_to_raw(snapshot, 1, placement_id=item["placementId"]) == (
        item["sourceId"],
        1,
    )
    fixtures._approve_fixture_sync(service, result["proposal"])
    ready = service.validate(prepared["importId"])
    activated = service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Qualify title activation",
    )
    assert activated["revision"]["snapshot"]["layout"] == snapshot["layout"]
