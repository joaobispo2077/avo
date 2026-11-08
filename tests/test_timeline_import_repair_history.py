"""Explicit same-export repair preserves staged history and canonical authority."""

import importlib.util
import json
import shutil
from copy import deepcopy

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import TimelineImportService
from avo.timeline.otio_import import ImportError, packet_identity
from tests.test_timeline_import_media import _mapping, _prepare
from tests.test_timeline_import_service import (
    FIXTURE,
    REFERENCE,
    _approve_fixture_sync,
    _probe,
)
from tests.test_timeline_import_service import import_project as _import_project

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="optional pinned native reader required",
)
SECOND_REFERENCE = "/tracks/children/0/children/1/media_reference"


@pytest.fixture(name="import_project")
def import_project_fixture(tmp_path):
    return _import_project.__wrapped__(tmp_path)


def _service(import_project):
    project, provider, _ = import_project
    return TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )


def _repair(service, export, predecessor, **options):
    return service.prepare(
        export,
        supersedes_import_id=predecessor,
        actor="editor",
        reason="Repair selected originals without replacing the edit",
        **options,
    )


def _files(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _locked_mapping(path):
    mapping = _mapping(path)
    fingerprint = file_fingerprint(path)
    mapping["fingerprint"] = {
        "path": str(path),
        "sha256": fingerprint["sha256"],
        "sizeBytes": fingerprint["sizeBytes"],
    }
    return mapping


def _two_sources(import_project, tmp_path):
    service = _service(import_project)
    original = import_project[2]
    second = original.parent / "second.mov"
    second.write_bytes(b"second original")
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first_clip = document["tracks"]["children"][0]["children"][0]
    second_clip = deepcopy(first_clip)
    second_clip["name"] = "Second occurrence"
    second_clip["media_reference"]["target_url"] = second.as_uri()
    document["tracks"]["children"][0]["children"].append(second_clip)
    export = tmp_path / "two-sources.otio"
    export.write_text(json.dumps(document), encoding="utf-8")
    mappings = {
        REFERENCE: _locked_mapping(original),
        SECOND_REFERENCE: _locked_mapping(second),
    }
    first = _prepare(service, export, roots=[original.parent], mappings=mappings)
    return service, export, first, original, second


def test_repair_keeps_verified_bytes_even_without_explicit_mapping_lock(import_project):
    service = _service(import_project)
    original = import_project[2]
    first = _prepare(service, FIXTURE, mappings={REFERENCE: _mapping(original)})
    validated = service.validate(first["importId"])
    assert validated["status"] == "awaiting-sync"
    original.write_bytes(b"different original bytes after predecessor validation")
    repaired = _repair(service, FIXTURE, first["importId"])
    result = service.validate(repaired["importId"])
    assert result["status"] == "blocked"
    assert any(row["code"] == "OTIO_SOURCE_CHANGED" for row in result["findings"])


def test_path_only_relink_preserves_routing_and_predecessor_fingerprint(
    import_project, tmp_path
):
    service = _service(import_project)
    original = import_project[2]
    first = _prepare(service, FIXTURE, mappings={REFERENCE: _mapping(original)})
    assert service.validate(first["importId"])["status"] == "awaiting-sync"
    moved = tmp_path / "relocated.mov"
    shutil.copyfile(original, moved)
    repaired = _repair(
        service,
        FIXTURE,
        first["importId"],
        mappings={REFERENCE: {"path": str(moved)}},
        media_roots=[str(tmp_path)],
    )
    mapping = repaired["session"]["options"]["mappings"][REFERENCE]
    assert mapping["videoStreamIndex"] == 0
    assert mapping["audioSelection"] == _mapping(original)["audioSelection"]
    assert mapping["fingerprint"]["sha256"] == file_fingerprint(original)["sha256"]
    assert service.validate(repaired["importId"])["status"] == "awaiting-sync"


def test_repair_inherits_omitted_options_and_binds_predecessor_into_identity(
    import_project,
):
    service = _service(import_project)
    first = _prepare(
        service,
        FIXTURE,
        roots=[import_project[2].parent],
        mappings={REFERENCE: _mapping(import_project[2])},
    )
    before = _files(service.root / first["importId"])
    repaired = _repair(service, FIXTURE, first["importId"])
    session = repaired["session"]
    assert repaired["importId"] != first["importId"]
    for key in ("mappings", "declarations", "mediaRoots"):
        assert session["options"][key] == first["session"]["options"][key]
    assert session["supersedesImportId"] == first["importId"]
    assert session["options"]["supersedesImportId"] == first["importId"]
    assert repaired["importId"] == packet_identity(
        session["source"]["sha256"],
        session["source"]["timelinePointer"],
        session["provider"],
        session["videoId"],
        session["options"],
        normalizer_version=session["normalizerVersion"],
    )
    assert _files(service.root / first["importId"]) == before
    assert not service.workspace.artifact_path("cmap").exists()


def test_identical_explicit_repair_is_idempotent_without_inheriting_old_receipt(
    import_project,
):
    service = _service(import_project)
    first = _prepare(
        service, FIXTURE, mappings={REFERENCE: _mapping(import_project[2])}
    )
    service.validate(first["importId"])
    repaired = _repair(service, FIXTURE, first["importId"])
    before = _files(service.root / first["importId"])
    retry = _repair(service, FIXTURE, first["importId"])
    assert retry["importId"] == repaired["importId"]
    assert retry["idempotent"] is True
    assert repaired["status"] == "prepared"
    assert (
        not {"validation", "proposal", "activation"}
        & repaired["session"]["refs"].keys()
    )
    assert retry["readiness"]["activationAllowed"] is False
    assert _files(service.root / first["importId"]) == before


def test_partial_mapping_repair_retains_unaffected_reference_and_structural_ids(
    import_project, tmp_path
):
    service, export, first, original, _ = _two_sources(import_project, tmp_path)
    previous = service.validate(first["importId"])
    before = _files(service.root / first["importId"])
    replacement = original.parent / "relinked-second.mov"
    replacement.write_bytes(b"explicit replacement for second source")
    repaired = _repair(
        service,
        export,
        first["importId"],
        mappings={SECOND_REFERENCE: _locked_mapping(replacement)},
    )
    options = repaired["session"]["options"]
    assert (
        options["mappings"][REFERENCE]
        == first["session"]["options"]["mappings"][REFERENCE]
    )
    assert options["mappings"][SECOND_REFERENCE]["path"] == str(replacement)
    result = service.validate(repaired["importId"])
    assert result["status"] == "awaiting-sync"
    old_segment = previous["proposal"]["snapshot"]["segments"][0]
    new_segment = result["proposal"]["snapshot"]["segments"][0]
    assert new_segment == old_segment
    assert {
        source["locator"] for source in result["proposal"]["snapshot"]["sources"]
    } == {str(original), str(replacement)}
    assert _files(service.root / first["importId"]) == before
    assert not service.workspace.artifact_path("cmap").exists()


def test_explicit_empty_media_roots_does_not_mean_omitted_inherited_roots(
    import_project,
):
    service = _service(import_project)
    first = _prepare(
        service,
        FIXTURE,
        roots=[import_project[2].parent],
        mappings={REFERENCE: _mapping(import_project[2])},
    )
    repaired = _repair(service, FIXTURE, first["importId"], media_roots=[])
    assert repaired["session"]["options"]["mediaRoots"] == []
    assert (
        repaired["session"]["options"]["mappings"]
        == first["session"]["options"]["mappings"]
    )


def test_changed_export_with_repair_flag_rejects_before_writes(
    import_project, tmp_path
):
    service = _service(import_project)
    first = _prepare(
        service, FIXTURE, mappings={REFERENCE: _mapping(import_project[2])}
    )
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["name"] = "Distinct exported handoff"
    changed = tmp_path / "changed.otio"
    changed.write_text(json.dumps(document), encoding="utf-8")
    before = _files(service.root)
    with pytest.raises(ImportError):
        _repair(service, changed, first["importId"])
    assert _files(service.root) == before


def test_changed_timeline_selection_with_repair_flag_rejects_before_writes(
    import_project, tmp_path
):
    service = _service(import_project)
    timeline = json.loads(FIXTURE.read_text(encoding="utf-8"))
    export = tmp_path / "collection.otio"
    export.write_text(
        json.dumps(
            {
                "OTIO_SCHEMA": "SerializableCollection.1",
                "children": [timeline, deepcopy(timeline)],
            }
        ),
        encoding="utf-8",
    )
    first = service.prepare(
        export, timeline="/children/0", actor="editor", reason="Select timeline"
    )
    before = _files(service.root)
    with pytest.raises(ImportError):
        _repair(service, export, first["importId"], timeline="/children/1")
    assert _files(service.root) == before


def test_missing_predecessor_cannot_create_packet(import_project):
    service = _service(import_project)
    before = _files(service.root)
    with pytest.raises(ImportError):
        _repair(service, FIXTURE, "f" * 64)
    assert _files(service.root) == before


def test_predecessor_from_another_target_cannot_be_adopted(import_project, tmp_path):
    service = _service(import_project)
    other_root = tmp_path / "other-target"
    other_root.mkdir()
    other = _import_project.__wrapped__(other_root)
    project = json.loads(other[0].read_text())
    project["videoId"] = "other-video"
    other[0].write_text(json.dumps(project))
    other_service = _service(other)
    foreign = _prepare(other_service, FIXTURE, mappings={REFERENCE: _mapping(other[2])})
    shutil.copytree(
        other_service.root / foreign["importId"], service.root / foreign["importId"]
    )
    before = _files(service.root)
    with pytest.raises(ImportError):
        _repair(service, FIXTURE, foreign["importId"])
    assert _files(service.root) == before


@pytest.mark.parametrize("tamper", ["option", "session", "missing-session-link"])
def test_predecessor_links_cannot_be_changed_outside_packet_identity(
    import_project, tamper
):
    service = _service(import_project)
    first = _prepare(
        service, FIXTURE, mappings={REFERENCE: _mapping(import_project[2])}
    )
    repaired = _repair(service, FIXTURE, first["importId"])
    path = service.packet_path(repaired["importId"])
    data = json.loads(path.read_text(encoding="utf-8"))
    if tamper == "option":
        data["options"]["supersedesImportId"] = "a" * 64
    elif tamper == "session":
        data["supersedesImportId"] = "a" * 64
    else:
        del data["supersedesImportId"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ImportError):
        service.load(repaired["importId"])


def test_repair_rechecks_unchanged_mapping_bytes_instead_of_reusing_prior_validation(
    import_project, tmp_path
):
    service, export, first, original, second = _two_sources(import_project, tmp_path)
    service.validate(first["importId"])
    original.write_bytes(b"unaffected filename now contains different source bytes")
    repaired = _repair(
        service,
        export,
        first["importId"],
        mappings={SECOND_REFERENCE: _locked_mapping(second)},
    )
    result = service.validate(repaired["importId"])
    assert result["status"] == "blocked"
    assert result["readiness"]["activationAllowed"] is False
    assert any(
        finding["code"] == "OTIO_SOURCE_CHANGED" for finding in result["findings"]
    )
    assert not service.workspace.artifact_path("cmap").exists()


def test_active_predecessor_is_history_only_and_never_selects_or_approves_repair(
    import_project,
):
    service = _service(import_project)
    first = _prepare(
        service, FIXTURE, mappings={REFERENCE: _mapping(import_project[2])}
    )
    waiting = service.validate(first["importId"])
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(first["importId"])
    service.activate(
        first["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture-editor",
        reason="Fixture draft selection",
    )
    cmap = service.workspace.store("cmap")
    before = cmap.load_index()
    repaired = _repair(service, FIXTURE, first["importId"])
    assert cmap.load_index() == before
    assert repaired["status"] == "prepared"
    assert repaired["readiness"]["activationAllowed"] is False
    assert not {"activation", "validation"} & repaired["session"]["refs"].keys()
    assert cmap.effective_approval() is None
