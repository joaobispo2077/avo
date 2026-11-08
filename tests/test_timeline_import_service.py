from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.provider_scaffold import build_manifest
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import TimelineImportService, _local_reference
from avo.timeline.otio_import import ImportError
from avo.timeline.sync_service import SyncService

FIXTURE = Path(__file__).parent / "fixtures/otio/clip-v1.otio"
REFERENCE = "/tracks/children/0/children/0/media_reference"


def _trial(service, original, export=FIXTURE):
    if importlib.util.find_spec("opentimelineio") is None:
        pytest.skip("Optional pinned native reader required")
    return service.prepare(
        export,
        mappings={
            REFERENCE: {
                "path": str(original),
                "identityConfirmed": True,
                "videoStreamIndex": 0,
                "audioSelection": {
                    "streamIndex": 1,
                    "channels": [0, 1],
                    "sourceLayout": "stereo",
                    "outputLayout": "stereo",
                },
            }
        },
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
        reason="Synthetic handoff",
    )


def _probe(paths):
    # Media properties are a test double; native fidelity uses real FFprobe below.
    return {
        "sources": [
            {
                "locator": str(path),
                "fingerprint": file_fingerprint(path),
                "durationSeconds": 100,
                "streams": {
                    "video": [
                        {
                            "index": 0,
                            "width": 640,
                            "height": 360,
                            "timeBase": "1/24",
                            "frameRate": "24/1",
                            "averageFrameRate": "24/1",
                            "durationTicks": 2400,
                            "startTimeSeconds": 0,
                            "clockVerification": {
                                "status": "verified",
                                "sourceSha256": file_fingerprint(path)["sha256"],
                                "streamIndex": 0,
                                "frameRate": {"num": 24, "den": 1},
                                "method": "explicit-fixture-test-double",
                                "packetCount": 2400,
                            },
                        }
                    ],
                    "audio": [
                        {
                            "index": 1,
                            "sampleRate": 48000,
                            "channels": 2,
                            "channelLayout": "stereo",
                            "durationTicks": 4800000,
                            "timeBase": "1/48000",
                            "startTimeSeconds": 0,
                        }
                    ],
                },
            }
            for path in paths
        ]
    }


def _approve_fixture_sync(service, proposal):
    # Explicit fixture-only decision, never production review evidence.
    sources = proposal["snapshot"]["sources"]
    sync = SyncService(service.workspace)
    revision = sync.author_not_applicable(
        raw_fingerprints={s["sourceId"]: s["fingerprint"]["sha256"] for s in sources},
        actor="test",
        reason="Synthetic muxed-clock fixture",
    )
    evidence = sync.validate_current()
    sync.decide(
        decision="approved",
        candidate_hash=revision["contentHash"],
        evidence_bundle_hash=evidence["sha256"],
        actor="fixture-reviewer",
        reason="Fixture-only N/A",
    )


def test_validate_builds_exact_proposal_without_canonical_activation(import_project):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = _trial(service, original)
    result = service.validate(prepared["importId"])
    assert result["status"] == "awaiting-sync"
    segment = result["proposal"]["snapshot"]["segments"][0]
    assert segment["in"]["ticks"] == 0  # available_range starts at 240@24
    assert (
        segment["out"]["ticks"]
        * segment["out"]["timebase"]["num"]
        / segment["out"]["timebase"]["den"]
        == 2
    )
    assert not service.workspace.artifact_path("cmap").exists()
    assert result["readiness"]["activationAllowed"] is False


@pytest.mark.parametrize("defect", ["short-audio", "delayed-audio"])
def test_selected_stream_extent_and_origin_must_match_imported_linkage(
    import_project, defect
):
    project, provider, original = import_project

    def defective_probe(paths):
        result = _probe(paths)
        audio = result["sources"][0]["streams"]["audio"][0]
        if defect == "short-audio":
            audio["durationTicks"] = 48000
        else:
            audio["startTimeSeconds"] = 1
        return result

    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=defective_probe
    )
    prepared = _trial(service, original)
    result = service.validate(prepared["importId"])
    assert result["status"] == "blocked"
    assert result["readiness"]["mediaReady"] == "failed"


def test_activation_requires_exact_receipt_sync_and_preserves_source_policy(
    import_project,
):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = _trial(service, original)
    waiting = service.validate(prepared["importId"])
    with pytest.raises(ImportError):
        service.activate(
            prepared["importId"],
            validation_hash=waiting["validationHash"],
            expected_head="empty",
            actor="editor",
            reason="Select draft",
        )
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    assert ready["readiness"]["activationAllowed"] is True
    with pytest.raises(ImportError):
        service.activate(
            prepared["importId"],
            validation_hash="a" * 64,
            expected_head="empty",
            actor="editor",
            reason="Wrong receipt",
        )
    active = service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="editor",
        reason="Select draft",
    )
    assert active["status"] == "active-draft"
    store = service.workspace.store("cmap")
    revision = store.revision(store.load_index()["headRevisionId"])
    assert revision["snapshot"]["originRef"]["importId"] == prepared["importId"]
    assert revision["snapshot"]["sourceAssemblyPolicy"] == "preserve-import"
    assert store.effective_approval() is None
    assert service.workspace.store("bmap").load_index()["headRevisionId"] is None
    from avo.timeline.pipeline import TimelinePipeline

    status = TimelinePipeline(service.workspace).initialize()
    assert status["timelineImport"]["originRef"]["importId"] == prepared["importId"]
    assert status["pipeline"]["mainState"] == "cmap-draft"
    assert store.load_index()["headRevisionId"] == revision["revisionId"]
    retry = service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="editor",
        reason="Retry",
    )
    assert retry["status"] == "active-draft"
    assert len(store.load_index()["revisionRefs"]) == 1


def test_changed_source_after_validation_cannot_activate(import_project):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = _trial(service, original)
    waiting = service.validate(prepared["importId"])
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    original.write_bytes(b"changed")
    with pytest.raises(ImportError):
        service.activate(
            prepared["importId"],
            validation_hash=ready["validationHash"],
            expected_head="empty",
            actor="editor",
            reason="Changed source",
        )
    assert service.workspace.store("cmap").load_index()["headRevisionId"] is None


def test_changed_latest_proposal_cannot_replace_exact_validated_proposal(
    import_project,
):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = _trial(service, original)
    waiting = service.validate(prepared["importId"])
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    changed = json.loads(json.dumps(ready["proposal"]))
    changed["snapshot"]["segments"][0]["in"]["ticks"] += 1
    session = service.load(prepared["importId"])
    session["refs"]["proposal"] = service._record(
        prepared["importId"], "proposals", changed
    )
    service._save(session)
    active = service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="editor",
        reason="Select the exact validated proposal",
    )
    assert (
        active["revision"]["snapshot"]["segments"]
        == ready["proposal"]["snapshot"]["segments"]
    )
    assert active["revision"]["snapshot"]["segments"] != changed["snapshot"]["segments"]


def test_changed_project_assignment_cannot_commit_cached_provider(import_project):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = _trial(service, original)
    waiting = service.validate(prepared["importId"])
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    settings = json.loads(project.read_text())
    settings["provider"] = "other"
    project.write_text(json.dumps(settings))
    with pytest.raises(ImportError):
        service.activate(
            prepared["importId"],
            validation_hash=ready["validationHash"],
            expected_head="empty",
            actor="editor",
            reason="Cached target must fail",
        )
    assert service.workspace.store("cmap").load_index()["headRevisionId"] is None


def test_activation_intent_cannot_impersonate_another_committed_import(import_project):

    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    first = _trial(service, original)
    waiting = service.validate(first["importId"])
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(first["importId"])
    raw = json.loads(FIXTURE.read_text())
    raw["metadata"] = {"trial": 2}
    second_export = project.parent / "second.otio"
    second_export.write_text(json.dumps(raw))
    second = _trial(service, original, second_export)
    second_ready = service.validate(second["importId"])
    session = service.load(second["importId"])
    intent = service._activation_intent(
        session, second_ready["validationHash"], "empty", "editor", "Second"
    )
    active = service.activate(
        first["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="editor",
        reason="First",
    )
    intent_path = service.packet_path(
        second["importId"], f"activation/{intent['operationId']}.json"
    )
    intent["operationId"] = active["activation"]["operationId"]
    intent_path.write_text(json.dumps(intent))
    with pytest.raises(ImportError) as error:
        service.activate(
            second["importId"],
            validation_hash=second_ready["validationHash"],
            expected_head="empty",
            actor="editor",
            reason="Second",
        )
    assert error.value.code == "OTIO_SOURCE_CHANGED"
    assert (
        service.workspace.store("cmap").head_hash() == active["revision"]["contentHash"]
    )
    current = service.validate(second["importId"])
    assert (
        current["validation"]["locks"]["expectedHeadHash"]
        == active["revision"]["contentHash"]
    )
    assert service.head_hash() == active["revision"]["contentHash"]


@pytest.mark.parametrize("after_commit", [False, True])
def test_interrupted_activation_reconciles_without_duplicate_append(
    import_project, monkeypatch, after_commit
):
    from avo.timeline.cmap_service import CMapService
    from avo.timeline.store import StoreError, timeline_writer

    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = _trial(service, original)
    waiting = service.validate(prepared["importId"])
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    author = CMapService.author

    def interrupt(self, *args, **kwargs):
        if after_commit:
            author(self, *args, **kwargs)
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(CMapService, "author", interrupt)
    with pytest.raises(ImportError) as error:
        service.activate(
            prepared["importId"],
            validation_hash=ready["validationHash"],
            expected_head="empty",
            actor="editor",
            reason="Select draft",
        )
    assert error.value.code == "OTIO_RECOVERY_REQUIRED"
    if after_commit:
        with pytest.raises(StoreError, match="RECOVERY_REQUIRED"):
            service.workspace.require_active("cmap")
        with pytest.raises(StoreError, match="RECOVERY_REQUIRED"):
            service.workspace.store("cmap").append_revision(
                snapshot={}, actor="ordinary-editor", reason="Blocked while pending"
            )
    else:
        assert not service._pending_path().exists()
        with timeline_writer(service.workspace.timeline_dir):
            assert (
                service.workspace.store("cmap").load_index()["headRevisionId"] is None
            )
    monkeypatch.setattr(CMapService, "author", author)
    active = service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="editor",
        reason="Retry",
    )
    assert active["status"] == "active-draft"
    assert len(service.workspace.store("cmap").load_index()["revisionRefs"]) == 1
    assert not service._pending_path().exists()


@pytest.fixture
def import_project(tmp_path):
    raw = tmp_path / "footage"
    raw.mkdir()
    original = raw / "take.mov"
    original.write_bytes(b"synthetic media placeholder, not probed during preparation")
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps({"provider": "channel", "videoId": "trial", "rawDir": str(raw)})
    )
    provider = tmp_path / "installation" / "providers" / "channel"
    provider.mkdir(parents=True)
    (provider / "avo.provider.json").write_text(
        json.dumps(build_manifest("channel", "youtube", str(raw)))
    )
    return project, provider, original


def test_prepare_retains_exact_export_without_canonical_heads(import_project):
    project, provider, original = import_project
    service = TimelineImportService(project, provider_root=provider)
    result = service.prepare(
        FIXTURE, media_roots=[original.parent], actor="editor", reason="Handoff"
    )
    packet = service.load(result["importId"])
    assert packet["state"] == "prepared"
    assert packet["expectedHeadHash"] == "empty"
    assert (
        service.root / result["importId"] / "source.otio"
    ).read_bytes() == FIXTURE.read_bytes()
    assert not (project.parent / "edit/timeline/cmap.json").exists()
    assert not (project.parent / "edit/timeline/pipeline-run.json").exists()


def test_preparation_does_not_call_native_reader_or_probe(import_project):
    project, provider, original = import_project

    def forbidden(*args):
        pytest.fail("Preparation cannot invoke semantic reading or probe media")

    service = TimelineImportService(
        project, provider_root=provider, reader=forbidden, probe=forbidden
    )
    service.prepare(
        FIXTURE, media_roots=[original.parent], actor="editor", reason="Inspect first"
    )


def test_identical_preparation_reuses_packet(import_project):
    project, provider, original = import_project
    service = TimelineImportService(project, provider_root=provider)
    first = service.prepare(
        FIXTURE, media_roots=[original.parent], actor="editor", reason="First"
    )
    second = service.prepare(
        FIXTURE, media_roots=[original.parent], actor="editor", reason="Retry"
    )
    assert second["importId"] == first["importId"]
    assert service.load(first["importId"])["reason"] == "First"


def test_provider_conflict_fails_before_writes(import_project):
    project, provider, _ = import_project
    with pytest.raises(ImportError) as error:
        TimelineImportService(project, provider="other", provider_root=provider)
    assert error.value.code == "OTIO_TARGET_CONFLICT"
    assert not (project.parent / "edit").exists()


def test_changed_declared_raw_dir_cannot_use_workspace_fallback(import_project):
    project, provider, _ = import_project
    (project.parent / "edit").mkdir()
    value = json.loads(project.read_text())
    value["rawDir"] = str(project.parent / "missing")
    project.write_text(json.dumps(value))
    with pytest.raises(ImportError) as error:
        TimelineImportService(project, provider_root=provider)
    assert error.value.code == "OTIO_TARGET_CONFLICT"
    assert not (project.parent / "edit/timeline/imports").exists()


def test_packet_path_traversal_and_tampering_fail(import_project):
    project, provider, original = import_project
    service = TimelineImportService(project, provider_root=provider)
    with pytest.raises(ImportError):
        service.load("../outside")
    result = service.prepare(
        FIXTURE, media_roots=[original.parent], actor="editor", reason="Handoff"
    )
    index = service.root / result["importId"] / "index.json"
    data = json.loads(index.read_text())
    data["options"]["mediaRoots"] = ["/changed"]
    index.write_text(json.dumps(data))
    with pytest.raises(ImportError):
        service.load(result["importId"])


def test_packet_provider_cannot_be_changed_by_editing_index(import_project):
    project, provider, original = import_project
    service = TimelineImportService(project, provider_root=provider)
    result = service.prepare(
        FIXTURE, media_roots=[original.parent], actor="editor", reason="Handoff"
    )
    index = service.root / result["importId"] / "index.json"
    data = json.loads(index.read_text())
    data["provider"] = "different"
    index.write_text(json.dumps(data))
    with pytest.raises(ImportError):
        service.load(result["importId"])


def test_relative_media_location_is_not_silently_resolved(import_project):
    project, provider, _ = import_project
    service = TimelineImportService(project, provider_root=provider)
    with pytest.raises(ImportError):
        service.prepare(
            FIXTURE, media_roots=["relative"], actor="editor", reason="Handoff"
        )
    assert not service.root.exists()


def test_file_uri_is_decoded_once_and_native_absolute_paths_are_accepted(tmp_path):
    path = tmp_path / "take%20v1.mov"
    assert _local_reference(path.as_uri()).resolve() == path.resolve()
    assert _local_reference(str(path)).resolve() == path.resolve()


def test_confirmed_local_mapping_can_repair_remote_reference_evidence(import_project):
    project, provider, original = import_project
    service = TimelineImportService(project, provider_root=provider)
    session = {
        "options": {
            "mappings": {REFERENCE: {"path": str(original), "identityConfirmed": True}},
            "mediaRoots": [],
        }
    }
    path, _ = service._source_path(
        {
            "referencePointer": REFERENCE,
            "targetUrl": "file://editor-machine/share/original.mov",
        },
        session,
    )
    assert path == original.resolve()


def test_decimal_declarations_survive_packet_reload(import_project):
    project, provider, original = import_project
    service = TimelineImportService(project, provider_root=provider)
    result = service.prepare(
        FIXTURE,
        media_roots=[original.parent],
        declarations={"gain": 0.5},
        actor="editor",
        reason="Handoff",
    )
    assert service.load(result["importId"])["options"]["declarations"]["gain"] == 0.5


@pytest.mark.parametrize("mappings", [["ref"], {"ref": []}, {"ref": {}}])
def test_malformed_mapping_is_structured_input_error(import_project, mappings):
    project, provider, _ = import_project
    service = TimelineImportService(project, provider_root=provider)
    with pytest.raises(ImportError) as error:
        service.prepare(FIXTURE, mappings=mappings, actor="editor", reason="Handoff")
    assert error.value.code == "OTIO_INPUT_INVALID"
    assert not service.root.exists()


def test_oversized_evidence_is_rejected_before_hashing(import_project, monkeypatch):
    project, provider, _ = import_project
    service = TimelineImportService(project, provider_root=provider)
    result = service.prepare(FIXTURE, actor="editor", reason="Handoff")
    session = service.load(result["importId"])
    export = service.packet_path(result["importId"], "source.otio")
    with export.open("r+b") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)

    def forbidden(*args):
        pytest.fail("Oversized input must be rejected before hashing")

    monkeypatch.setattr("avo.timeline.import_service.hashlib.sha256", forbidden)
    with pytest.raises(ImportError) as error:
        service.read_ref(result["importId"], session["refs"]["export"])
    assert error.value.code == "OTIO_INPUT_LIMIT"
