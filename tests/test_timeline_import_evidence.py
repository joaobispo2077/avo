"""Activated import evidence survives scoped edits without trusting session refs."""

import json
from copy import deepcopy
from functools import partial

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import content_hash
from avo.timeline.import_evidence import verify_import_origin
from avo.timeline.import_service import TimelineImportService
from avo.timeline.otio_import import packet_identity
from tests.test_timeline_import_service import (
    _approve_fixture_sync,
    _probe,
    _trial,
)
from tests.test_timeline_import_service import (
    import_project as _import_project,
)


@pytest.fixture
def evidence_import(tmp_path):
    return _prepare_evidence(tmp_path)


def _prepare_evidence(tmp_path):
    project, provider, original = _import_project.__wrapped__(tmp_path)
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = _trial(service, original)
    waiting = service.validate(prepared["importId"])
    # These are explicit fixture-only media facts and Sync decisions.
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    return service, ready


def _activate(service, ready):
    return service.activate(
        ready["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Select evidence fixture",
    )["revision"]


def _packet_files(service, ready, revision):
    origin = revision["snapshot"]["originRef"]
    packet = service.root / ready["importId"]
    return {
        "intent": packet / "activation" / f"{origin['activationId']}.json",
        "receipt": packet / "validations" / f"{ready['validationHash']}.json",
        "proposal": packet / "proposals" / f"{content_hash(ready['proposal'])}.json",
        "export": packet / "source.otio",
    }


def test_verified_activation_returns_exact_immutable_evidence(evidence_import):
    service, ready = evidence_import
    revision = _activate(service, ready)
    paths = verify_import_origin(service.workspace, revision)
    assert set(_packet_files(service, ready, revision).values()) <= set(paths)
    assert all(path.is_file() for path in paths)
    assert any(path.parent.name == "activation-results" for path in paths)


@pytest.mark.parametrize("kind", ["intent", "receipt", "proposal", "export"])
@pytest.mark.parametrize("damage", ["missing", "tampered"])
def test_missing_or_tampered_evidence_blocks(evidence_import, kind, damage):
    service, ready = evidence_import
    revision = _activate(service, ready)
    path = _packet_files(service, ready, revision)[kind]
    if damage == "missing":
        path.unlink()
    elif kind == "export":
        path.write_bytes(path.read_bytes() + b" ")
    else:
        value = json.loads(path.read_text())
        value["schemaVersion"] = "99.0.0"
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="import evidence|Import evidence"):
        verify_import_origin(service.workspace, revision)


def test_scoped_descendant_survives_mutable_session_reference_updates(evidence_import):
    service, ready = evidence_import
    revision = _activate(service, ready)
    snapshot = deepcopy(revision["snapshot"])
    snapshot["segments"][0]["out"]["ticks"] -= 1
    descendant = CMapService(service.workspace).author(
        snapshot, actor="fixture", reason="Requested scoped trim"
    )
    # A later validation changes mutable proposal/receipt refs, not the activation.
    service.validate(ready["importId"])
    paths = verify_import_origin(service.workspace, descendant)
    assert _packet_files(service, ready, revision)["receipt"] in paths


def test_fabricated_capability_version_blocks(evidence_import):
    service, ready = evidence_import
    revision = _activate(service, ready)
    snapshot = deepcopy(revision["snapshot"])
    snapshot["originRef"]["capabilityVersion"] = "unknown-9.0.0"
    descendant = CMapService(service.workspace).author(
        snapshot, actor="fixture", reason="Unsupported capability fixture"
    )
    with pytest.raises(ValueError, match="capability|Capability"):
        verify_import_origin(service.workspace, descendant)


def test_staged_ready_packet_does_not_impersonate_reconciled_activation(
    evidence_import,
):
    service, ready = evidence_import
    session = service.load(ready["importId"])
    intent = service._activation_intent(
        session, ready["validationHash"], "empty", "fixture", "Uncommitted fixture"
    )
    snapshot = service._selected_snapshot(session, ready["proposal"], intent)
    revision = CMapService(service.workspace).author(
        snapshot,
        revision_id=intent["revisionId"],
        created_at=intent["createdAt"],
        actor=intent["actor"],
        reason=intent["reason"],
    )
    with pytest.raises(ValueError, match="reconcil|activation"):
        verify_import_origin(service.workspace, revision)


def test_manifest_nonidentity_change_keeps_activated_provenance(evidence_import):
    service, ready = evidence_import
    revision = _activate(service, ready)
    project = json.loads(service.workspace.project_path.read_text())
    project["description"] = "Harmless current brief note"
    service.workspace.project_path.write_text(json.dumps(project))
    assert verify_import_origin(service.workspace, revision)


@pytest.mark.parametrize(
    "field,value", [("provider", "another"), ("videoId", "another")]
)
def test_changed_current_target_identity_cannot_use_cached_workspace(
    evidence_import, field, value
):
    service, ready = evidence_import
    revision = _activate(service, ready)
    project = json.loads(service.workspace.project_path.read_text())
    project[field] = value
    service.workspace.project_path.write_text(json.dumps(project))
    with pytest.raises(ValueError, match="identity"):
        verify_import_origin(service.workspace, revision)


def test_missing_reconciliation_receipt_is_not_an_activated_import(evidence_import):
    service, ready = evidence_import
    revision = _activate(service, ready)
    paths = verify_import_origin(service.workspace, revision)
    next(path for path in paths if path.parent.name == "activation-results").unlink()
    with pytest.raises(ValueError, match="activation-results|reconcil"):
        verify_import_origin(service.workspace, revision)


def test_output_clock_and_routing_are_bound_but_scaled_preview_is_allowed(
    evidence_import,
):
    service, ready = evidence_import
    revision = _activate(service, ready)
    output = deepcopy(revision["snapshot"]["importOutput"])
    output.update(width=320, height=180)
    # Key order is not the rational value's meaning.
    output["frameRate"] = {"den": 1, "num": 24}
    assert verify_import_origin(service.workspace, revision, output=output)
    output["frameRate"]["num"] = 25
    with pytest.raises(ValueError, match="clock"):
        verify_import_origin(service.workspace, revision, output=output)


def test_ordinary_canonical_snapshot_needs_no_import_packet():
    assert verify_import_origin(None, {"snapshot": {}}) == []


def test_legacy_normalizer_one_packet_without_root_locks_remains_verifiable(
    tmp_path, monkeypatch
):
    from avo.timeline import import_service

    original_context = TimelineImportService._read_context_lock

    def legacy_context(service):
        context = original_context(service)
        context.pop("timelineRoot")
        context.pop("importsRoot")
        return context

    monkeypatch.setattr(import_service, "NORMALIZER_VERSION", "1.0.0")
    monkeypatch.setattr(
        import_service,
        "packet_identity",
        partial(packet_identity, normalizer_version="1.0.0"),
    )
    monkeypatch.setattr(TimelineImportService, "_read_context_lock", legacy_context)
    service, ready = _prepare_evidence(tmp_path)
    revision = _activate(service, ready)
    assert "timelineRoot" not in ready["validation"]["locks"]["context"]
    assert verify_import_origin(service.workspace, revision)
