"""US2 relink behavior; candidates are evidence, never source identity approval."""

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import TimelineImportService, _local_reference
from avo.timeline.otio_import import ImportError
from tests.test_timeline_import_service import FIXTURE, REFERENCE, _probe
from tests.test_timeline_import_service import import_project as _import_project

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="optional pinned native reader required",
)


@pytest.fixture(name="import_project")
def import_project_fixture(tmp_path):
    return _import_project.__wrapped__(tmp_path)


def _export(tmp_path, target_url):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["tracks"]["children"][0]["children"][0]["media_reference"][
        "target_url"
    ] = target_url
    path = tmp_path / "handoff.otio"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _prepare(service, export, *, roots=(), mappings=None):
    return service.prepare(
        export,
        media_roots=roots,
        mappings=mappings,
        declarations={
            "sourceOnly": True,
            "output": {
                "width": 640,
                "height": 360,
                "frameRate": {"num": 24, "den": 1},
                "audioSampleRate": 48000,
                "channelLayout": "stereo",
            },
        },
        actor="editor",
        reason="Inspect relocated original candidates",
    )


def _mapping(path, *, confirmed=True):
    return {
        "path": str(path),
        "identityConfirmed": confirmed,
        "videoStreamIndex": 0,
        "audioSelection": {
            "streamIndex": 1,
            "channels": [0, 1],
            "sourceLayout": "stereo",
            "outputLayout": "stereo",
        },
    }


def _service(import_project, probe=_probe):
    project, provider, _ = import_project
    return TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=probe
    )


@pytest.mark.parametrize(
    "url",
    [
        r"\\server\share\take.mov",
        "//server/share/take.mov",
        "file://server/share/take.mov",
        "file:////server/share/take.mov",
        "file:///%5C%5Cserver%5Cshare%5Ctake.mov",
    ],
)
def test_network_share_spelling_is_rejected_before_any_resolution(url):
    with pytest.raises(ImportError) as error:
        _local_reference(url)
    assert error.value.code == "OTIO_SOURCE_PROHIBITED"


def test_explicit_replacement_root_reports_candidate_without_selecting_filename(
    import_project, tmp_path
):
    root = tmp_path / "relocated"
    root.mkdir()
    candidate = root / "take.mov"
    candidate.write_bytes(b"candidate original")
    service = _service(import_project)
    prepared = _prepare(service, FIXTURE, roots=[root])

    result = service.validate(prepared["importId"])
    assert result["status"] == "blocked"
    assert result["readiness"]["activationAllowed"] is False
    mapping = result["mediaMappings"][REFERENCE]
    assert mapping["status"] == "unresolved"
    assert not mapping.get("selected")
    assert len(mapping["candidates"]) == 1
    found = mapping["candidates"][0]
    assert found["path"] == str(candidate.resolve())
    assert found["matchBasis"] == "filename-only"
    assert found["fingerprint"]["sha256"] == file_fingerprint(candidate)["sha256"]
    assert found["properties"]["durationSeconds"] == 100
    assert not service.workspace.artifact_path("cmap").exists()


def test_duplicate_filenames_keep_distinct_byte_identities_and_require_choice(
    import_project, tmp_path
):
    roots = [tmp_path / "camera-a", tmp_path / "camera-b"]
    for index, root in enumerate(roots):
        root.mkdir()
        (root / "take.mov").write_bytes(f"different camera {index}".encode())
    service = _service(import_project)
    prepared = _prepare(service, FIXTURE, roots=roots)
    result = service.validate(prepared["importId"])
    mapping = result["mediaMappings"][REFERENCE]
    assert mapping["status"] == "ambiguous"
    assert not mapping.get("selected")
    assert {item["path"] for item in mapping["candidates"]} == {
        str((root / "take.mov").resolve()) for root in roots
    }
    assert len({item["fingerprint"]["sha256"] for item in mapping["candidates"]}) == 2
    assert all(item["matchBasis"] == "filename-only" for item in mapping["candidates"])
    assert any(
        finding["code"] == "OTIO_MEDIA_AMBIGUOUS" for finding in result["findings"]
    )


def test_candidate_repair_is_explicit_per_reference_and_preserves_prior_packet(
    import_project, tmp_path
):
    root = tmp_path / "moved"
    root.mkdir()
    chosen = root / "take.mov"
    chosen.write_bytes(b"chosen moved original")
    service = _service(import_project)
    first = _prepare(service, FIXTURE, roots=[root])
    service.validate(first["importId"])
    prior = deepcopy(service.load(first["importId"]))
    repaired = _prepare(
        service, FIXTURE, roots=[root], mappings={REFERENCE: _mapping(chosen)}
    )
    result = service.validate(repaired["importId"])
    assert repaired["importId"] != first["importId"]
    assert service.load(first["importId"]) == prior
    assert result["status"] == "awaiting-sync"
    assert result["mediaMappings"][REFERENCE]["status"] == "verified"
    assert result["readiness"]["activationAllowed"] is False
    assert result["proposal"]["snapshot"]["sources"][0]["locator"] == str(chosen)


def test_candidate_discovery_decodes_unicode_file_uri_basename(
    import_project, tmp_path
):
    root = tmp_path / "mídia recuperada"
    root.mkdir()
    chosen = root / "ação café #1.mov"
    chosen.write_bytes(b"unicode candidate")
    export = _export(tmp_path, (tmp_path / "old" / chosen.name).as_uri())
    service = _service(import_project)
    result = service.validate(_prepare(service, export, roots=[root])["importId"])
    assert [
        candidate["path"]
        for candidate in result["mediaMappings"][REFERENCE]["candidates"]
    ] == [str(chosen)]


@pytest.mark.parametrize("style", ["absolute", "file-uri", "localhost-file-uri", "wsl"])
def test_local_reference_forms_resolve_same_unicode_file_within_authorized_root(
    import_project, style
):
    service = _service(import_project)
    original = import_project[2].parent / "ação café.mov"
    original.write_bytes(b"unicode local original")
    if style == "wsl":
        if sys.platform != "win32":
            pytest.skip("Windows mount spelling is meaningful only on Windows")
        target = f"/mnt/{original.drive[0].lower()}/" + "/".join(original.parts[1:])
    elif style == "file-uri":
        target = original.as_uri()
    elif style == "localhost-file-uri":
        target = original.as_uri().replace("file:///", "file://localhost/", 1)
    else:
        target = str(original)
    path, mapping = service._source_path(
        {"referencePointer": REFERENCE, "targetUrl": target},
        {"options": {"mappings": {}, "mediaRoots": [str(original.parent)]}},
    )
    assert path == original.resolve()
    assert mapping == {}


def test_candidate_search_never_probes_undeclared_siblings_or_symlink_escape(
    import_project, tmp_path
):
    root, outside = tmp_path / "allowed", tmp_path / "private"
    root.mkdir()
    outside.mkdir()
    escaped = outside / "take.mov"
    escaped.write_bytes(b"outside authorized root")
    try:
        (root / "take.mov").symlink_to(escaped)
    except OSError:
        pytest.skip("symlink creation unavailable")
    probed = []

    def probe(paths):
        probed.extend(paths)
        return _probe(paths)

    service = _service(import_project, probe)
    result = service.validate(_prepare(service, FIXTURE, roots=[root])["importId"])
    assert result["status"] == "blocked"
    assert result["mediaMappings"][REFERENCE]["candidates"] == []
    assert escaped.resolve() not in {Path(path).resolve() for path in probed}


def test_source_symlink_cannot_escape_declared_root_without_explicit_file_mapping(
    import_project, tmp_path
):
    service = _service(import_project)
    outside = tmp_path / "outside.mov"
    outside.write_bytes(b"outside")
    link = import_project[2].parent / "linked.mov"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ImportError) as error:
        service._source_path(
            {"referencePointer": REFERENCE, "targetUrl": link.as_uri()},
            {"options": {"mappings": {}, "mediaRoots": []}},
        )
    assert error.value.code == "OTIO_MEDIA_MISSING"


def test_candidate_reports_are_bounded_and_truncation_blocks_selection(
    import_project, tmp_path
):
    root = tmp_path / "many"
    root.mkdir()
    for index in range(65):
        directory = root / str(index)
        directory.mkdir()
        (directory / "take.mov").write_bytes(str(index).encode())
    service = _service(import_project)
    result = service.validate(_prepare(service, FIXTURE, roots=[root])["importId"])
    assert result["status"] == "blocked"
    assert len(result["mediaMappings"][REFERENCE]["candidates"]) <= 64
    assert any(finding["code"] == "OTIO_INPUT_LIMIT" for finding in result["findings"])
