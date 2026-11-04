"""Native media relinking preserves explicit identity, scope, and staged history."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from copy import deepcopy

import pytest
from tests.test_timeline_import_service import FIXTURE, _approve_fixture_sync

from avo.adapters.media.ffprobe import FfprobeMediaAdapter
from avo.adapters.media.otio_reader import read_otio
from avo.provider_scaffold import build_manifest
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import TimelineImportService
from avo.timeline.otio_import import ImportError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        importlib.util.find_spec("opentimelineio") is None
        or not shutil.which("ffmpeg")
        or not shutil.which("ffprobe"),
        reason="Pinned OTIO and native FFmpeg/FFprobe required",
    ),
]
FIRST = "/tracks/children/0/children/0/media_reference"
SECOND = "/tracks/children/0/children/1/media_reference"
AUDIO = "/tracks/children/1/children/0/media_reference"


def _recording(path, frequency):
    path.parent.mkdir(parents=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            f"color={'red' if frequency == 440 else 'blue'}:s=128x96:r=24:d=3",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc=0.1*sin({frequency}*2*PI*t)|0.05*sin({frequency * 2}*2*PI*t):s=48000:d=3",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


@pytest.fixture
def trial(tmp_path):
    raw = tmp_path / "footage"
    raw.mkdir()
    paths = [
        tmp_path / "relocated-a" / "take.mkv",
        tmp_path / "relocated-b" / "take.mkv",
    ]
    for path, frequency in zip(paths, (440, 880), strict=True):
        _recording(path, frequency)
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps(
            {"provider": "channel", "videoId": "native-relink", "rawDir": str(raw)}
        ),
        encoding="utf-8",
    )
    provider = tmp_path / "provider"
    provider.mkdir()
    (provider / "avo.provider.json").write_text(
        json.dumps(build_manifest("channel", "youtube", str(raw))), encoding="utf-8"
    )
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first = document["tracks"]["children"][0]["children"][0]
    first["source_range"]["start_time"]["value"] = 264
    first["source_range"]["duration"]["value"] = 24
    first["media_reference"]["available_range"]["duration"]["value"] = 72
    first["media_reference"]["target_url"] = (
        tmp_path / "offline-a" / "take.mkv"
    ).as_uri()
    second = deepcopy(first)
    second["name"] = "Second independent original"
    second["media_reference"]["target_url"] = (
        tmp_path / "offline-b" / "take.mkv"
    ).as_uri()
    document["tracks"]["children"][0]["children"].append(second)
    export = raw / "handoff.otio"
    export.write_text(json.dumps(document), encoding="utf-8")
    service = TimelineImportService(
        project,
        provider_root=provider,
        reader=read_otio,
        probe=FfprobeMediaAdapter().inventory,
    )
    return service, export, paths


def _declarations(*, placed=False):
    value = {
        "sourceOnly": True,
        "output": {
            "width": 128,
            "height": 96,
            "frameRate": {"num": 24, "den": 1},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
        },
    }
    if placed:
        value["layoutMode"] = "placed"
    return value


def _prepare(service, export, paths, **options):
    return service.prepare(
        export,
        media_roots=[path.parent for path in paths],
        declarations=_declarations(),
        actor="fixture-editor",
        reason="Inspect explicitly relocated synthetic originals",
        **options,
    )


def _mapping(path, *, fingerprint=None, kind="muxed"):
    actual = file_fingerprint(path)
    mapping = {
        "path": str(path),
        "identityConfirmed": True,
        "fingerprint": fingerprint
        or {
            "path": str(path),
            "sha256": actual["sha256"],
            "sizeBytes": actual["sizeBytes"],
        },
    }
    if kind != "audio":
        mapping["videoStreamIndex"] = 0
    if kind != "video":
        mapping["audioSelection"] = {
            "streamIndex": 1,
            "channels": [0, 1],
            "sourceLayout": "stereo",
            "outputLayout": "stereo",
        }
    return mapping


def _packet_bytes(service, import_id):
    root = service.root / import_id
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _assert_preserved(service, import_id, before):
    current = _packet_bytes(service, import_id)
    assert all(current[name] == value for name, value in before.items())


def _hashes(paths):
    return [file_fingerprint(path)["sha256"] for path in paths]


def test_native_moved_and_duplicate_names_stay_unselected_evidence(trial):
    service, export, paths = trial
    originals, original_export = _hashes(paths), export.read_bytes()
    single = _prepare(service, export, paths[:1])
    unresolved = service.validate(single["importId"])
    for reference in (FIRST, SECOND):
        mapping = unresolved["mediaMappings"][reference]
        assert mapping["status"] == "unresolved"
        assert not mapping.get("selected")
        assert len(mapping["candidates"]) == 1
        candidate = mapping["candidates"][0]
        assert candidate["fingerprint"]["sha256"] == originals[0]
        assert candidate["properties"]["durationSeconds"] == 3
        assert candidate["properties"]["streams"]["audio"][0]["sampleRate"] == 48000
    before = _packet_bytes(service, single["importId"])
    duplicate = service.prepare(
        export,
        supersedes_import_id=single["importId"],
        media_roots=[path.parent for path in paths],
        actor="fixture-editor",
        reason="Inspect both explicit replacement folders",
    )
    ambiguous = service.validate(duplicate["importId"])
    assert ambiguous["status"] == "blocked"
    assert ambiguous["readiness"]["activationAllowed"] is False
    for reference in (FIRST, SECOND):
        mapping = ambiguous["mediaMappings"][reference]
        assert mapping["status"] == "ambiguous"
        assert not mapping.get("selected")
        assert {item["fingerprint"]["sha256"] for item in mapping["candidates"]} == set(
            originals
        )
        assert all(
            item["matchBasis"] == "filename-only" for item in mapping["candidates"]
        )
    assert service.head_hash() == "empty"
    assert _hashes(paths) == originals
    assert export.read_bytes() == original_export
    assert _packet_bytes(service, single["importId"]) == before


def test_native_partial_second_repair_preserves_first_scope_and_prior_packets(trial):
    service, export, paths = trial
    originals, original_export = _hashes(paths), export.read_bytes()
    first = _prepare(service, export, paths)
    unresolved = service.validate(first["importId"])
    initial_bytes = _packet_bytes(service, first["importId"])
    chosen = {}
    for reference, path in zip((FIRST, SECOND), paths, strict=True):
        candidate = next(
            item
            for item in unresolved["mediaMappings"][reference]["candidates"]
            if item["path"] == str(path)
        )
        chosen[reference] = _mapping(path, fingerprint=candidate["fingerprint"])
    selected = service.prepare(
        export,
        supersedes_import_id=first["importId"],
        mappings=chosen,
        actor="fixture-editor",
        reason="Explicitly choose both original identities",
    )
    previous = service.validate(selected["importId"])
    assert previous["status"] == "awaiting-sync"
    assert all(
        previous["mediaMappings"][ref]["status"] == "verified"
        for ref in (FIRST, SECOND)
    )
    previous_bytes = _packet_bytes(service, selected["importId"])
    replacement = paths[1].with_name("renamed-second.mkv")
    paths[1].rename(replacement)
    repaired = service.prepare(
        export,
        supersedes_import_id=selected["importId"],
        mappings={SECOND: _mapping(replacement)},
        actor="fixture-editor",
        reason="Relink only the second occurrence after a folder move",
    )
    assert len({first["importId"], selected["importId"], repaired["importId"]}) == 3
    assert (
        repaired["session"]["options"]["mappings"][FIRST]
        == selected["session"]["options"]["mappings"][FIRST]
    )
    waiting = service.validate(repaired["importId"])
    assert waiting["status"] == "awaiting-sync"
    assert (
        waiting["proposal"]["snapshot"]["segments"][0]
        == previous["proposal"]["snapshot"]["segments"][0]
    )
    assert (
        waiting["mediaMappings"][FIRST]["selected"]
        == previous["mediaMappings"][FIRST]["selected"]
    )
    assert waiting["mediaMappings"][SECOND]["selected"]["path"] == str(replacement)
    # These generated muxed clocks receive only a fixture-scoped Sync N/A decision.
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(repaired["importId"])
    assert ready["status"] == "ready-to-activate"
    active = service.activate(
        repaired["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture-editor",
        reason="Select synthetic repaired draft only",
    )
    assert active["status"] == "active-draft"
    cmap = service.workspace.store("cmap")
    snapshot = cmap.revision(cmap.load_index()["headRevisionId"])["snapshot"]
    assert [segment["in"]["ticks"] for segment in snapshot["segments"]] == [24, 24]
    assert [segment["out"]["ticks"] for segment in snapshot["segments"]] == [48, 48]
    assert snapshot["originRef"]["importId"] == repaired["importId"]
    assert cmap.effective_approval() is None
    assert _hashes([paths[0], replacement]) == originals
    assert export.read_bytes() == original_export
    assert _packet_bytes(service, first["importId"]) == initial_bytes
    assert _packet_bytes(service, selected["importId"]) == previous_bytes


def test_native_missing_explicit_microphone_blocks_until_exact_file_is_restored(trial):
    service, export, paths = trial
    originals = _hashes(paths)
    document = json.loads(export.read_text(encoding="utf-8"))
    picture = document["tracks"]["children"][0]
    picture["children"][1]["media_reference"] = deepcopy(
        picture["children"][0]["media_reference"]
    )
    microphone = deepcopy(picture)
    microphone["kind"] = "Audio"
    microphone["children"] = [deepcopy(picture["children"][0])]
    microphone["children"][0]["media_reference"]["target_url"] = (
        paths[1].parent / "offline-microphone.mkv"
    ).as_uri()
    document["tracks"]["children"].append(microphone)
    export.write_text(json.dumps(document), encoding="utf-8")
    original_export = export.read_bytes()
    prepared = service.prepare(
        export,
        media_roots=[path.parent for path in paths],
        mappings={
            FIRST: _mapping(paths[0], kind="video"),
            SECOND: _mapping(paths[0], kind="video"),
            AUDIO: _mapping(paths[1], kind="audio"),
        },
        declarations=_declarations(placed=True),
        actor="fixture-editor",
        reason="Preserve an explicit independent microphone track",
    )
    parked = paths[1].with_name("temporarily-absent.mkv")
    paths[1].rename(parked)
    blocked = service.validate(prepared["importId"])
    assert blocked["status"] == "blocked"
    assert any(
        item["code"] == "OTIO_MEDIA_MISSING" and item["scope"] == AUDIO
        for item in blocked["findings"]
    )
    assert service.head_hash() == "empty"
    immutable = {
        name: value
        for name, value in _packet_bytes(service, prepared["importId"]).items()
        if name != "index.json"
    }
    parked.rename(paths[1])
    waiting = service.validate(prepared["importId"])
    assert waiting["status"] == "awaiting-sync"
    assert waiting["mediaMappings"][AUDIO]["status"] == "verified"
    assert waiting["mediaMappings"][AUDIO]["selected"]["path"] == str(paths[1])
    assert len(waiting["proposal"]["snapshot"]["layout"]["placements"]) == 3
    _approve_fixture_sync(service, waiting["proposal"])
    assert service.validate(prepared["importId"])["status"] == "ready-to-activate"
    assert service.head_hash() == "empty"
    _assert_preserved(service, prepared["importId"], immutable)
    assert _hashes(paths) == originals
    assert export.read_bytes() == original_export


def test_native_changed_source_cannot_activate_cached_ready_validation(trial):
    service, export, paths = trial
    original_bytes = paths[1].read_bytes()
    originals, original_export = _hashes(paths), export.read_bytes()
    prepared = _prepare(
        service,
        export,
        paths,
        mappings={FIRST: _mapping(paths[0]), SECOND: _mapping(paths[1])},
    )
    waiting = service.validate(prepared["importId"])
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    assert ready["status"] == "ready-to-activate"
    before = _packet_bytes(service, prepared["importId"])
    paths[1].write_bytes(original_bytes + b"different current source bytes")
    assert file_fingerprint(paths[1])["sha256"] != originals[1]
    with pytest.raises(ImportError) as error:
        service.activate(
            prepared["importId"],
            validation_hash=ready["validationHash"],
            expected_head="empty",
            actor="fixture-editor",
            reason="Attempt selection with an outdated receipt",
        )
    assert error.value.code == "OTIO_SOURCE_CHANGED"
    assert service.head_hash() == "empty"
    assert service.workspace.store("cmap").load_index()["headRevisionId"] is None
    _assert_preserved(service, prepared["importId"], before)
    paths[1].write_bytes(original_bytes)
    assert _hashes(paths) == originals
    assert export.read_bytes() == original_export
