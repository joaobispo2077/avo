"""Read-only import status follows canonical activation, not mutable packet selection."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import TimelineImportService
from avo.timeline.workspace import TimelineWorkspace
from tests.test_timeline_import_placed_service import _prepare as _prepare_placed
from tests.test_timeline_import_service import _approve_fixture_sync, _probe, _trial
from tests.test_timeline_import_service import import_project as _import_project


def _tree(root):
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def _active(tmp_path, *, placed=False):
    pytest.importorskip("opentimelineio")
    project, provider, original = _import_project.__wrapped__(tmp_path)
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = (
        _prepare_placed(service, tmp_path / "placed.otio", original)
        if placed
        else _trial(service, original)
    )
    waiting = service.validate(prepared["importId"])
    # Explicit synthetic media facts and fixture-only Sync review.
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    activated = service.activate(
        ready["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Select source-only synthetic status fixture",
    )
    return service, ready, activated["revision"]


def test_ordinary_project_status_does_not_create_or_select_an_import(tmp_path):
    project, _, _ = _import_project.__wrapped__(tmp_path)
    workspace = TimelineWorkspace.from_project(project)
    before = _tree(tmp_path)
    assert workspace.timeline_import_status() is None
    assert "timelineImport" not in workspace.status()
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("placed", [False, True])
def test_import_status_exposes_exact_activation_refs_and_layout_without_writes(
    tmp_path, placed
):
    service, ready, revision = _active(tmp_path, placed=placed)
    before = _tree(tmp_path)
    restarted = TimelineWorkspace.from_project(service.workspace.project_path)
    status = restarted.status()["timelineImport"]
    assert status["status"] == "active-draft"
    assert status["capabilityLevel"] == (
        "placed-experimental" if placed else "contiguous-experimental"
    )
    assert status["originRef"] == revision["snapshot"]["originRef"]
    assert status["provider"] == "channel"
    assert status["videoId"] == service.workspace.video_id
    assert status["currentCanonical"] == {
        "revisionId": revision["revisionId"],
        "contentHash": revision["contentHash"],
    }
    assert status["source"] == ready["session"]["source"]
    assert status["compatibilityState"] == "verified-activation"
    assert status["recoveryRequired"] is False
    assert status["blockers"] == []
    assert status["pendingFinishing"] == []
    assert status["reviewState"] == "normal-current-candidate-gates-required"
    packet = status["packet"]
    assert packet["importId"] == ready["importId"]
    assert Path(packet["path"]) == service.root / ready["importId"]
    assert set(packet["refs"]) == {
        "session",
        "export",
        "activation",
        "validation",
        "proposal",
        "activationResult",
    }
    assert (
        packet["refs"]["validation"]["path"]
        == f"validations/{ready['validationHash']}.json"
    )
    for reference in packet["refs"].values():
        actual = file_fingerprint(Path(packet["path"]) / reference["path"])
        assert {key: actual[key] for key in ("sha256", "sizeBytes")} == {
            key: reference[key] for key in ("sha256", "sizeBytes")
        }
    assert service.workspace.store("cmap").effective_approval() is None
    assert _tree(tmp_path) == before


def test_import_status_keeps_activated_receipt_after_later_revalidation(tmp_path):
    service, ready, _ = _active(tmp_path)
    latest = service.validate(ready["importId"])
    assert latest["validationHash"] != ready["validationHash"]
    assert (
        latest["session"]["refs"]["validation"]["path"]
        != f"validations/{ready['validationHash']}.json"
    )
    before = _tree(tmp_path)
    status = service.workspace.timeline_import_status()
    assert status["compatibilityState"] == "verified-activation"
    assert (
        status["packet"]["refs"]["validation"]["path"]
        == f"validations/{ready['validationHash']}.json"
    )
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_invalid_activation_evidence_is_a_bounded_read_only_blocker(tmp_path, damage):
    service, ready, _ = _active(tmp_path)
    path = (
        service.root
        / ready["importId"]
        / "validations"
        / f"{ready['validationHash']}.json"
    )
    if damage == "missing":
        path.unlink()
    else:
        path.write_text(json.dumps({"privateContent": "must-not-dump" * 10000}))
    before = _tree(tmp_path)
    status = service.workspace.status()["timelineImport"]
    assert status["status"] == "blocked"
    assert status["compatibilityState"] == "blocked"
    assert status["blockers"][0]["code"] == "OTIO_SOURCE_CHANGED"
    assert status["pendingFinishing"] == []
    assert "must-not-dump" not in json.dumps(status)
    assert len(json.dumps(status).encode()) < 16384
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(
    "contents", ["{", "x" * 5000, '{"importId":"invalid","operationId":"invalid"}']
)
def test_corrupt_pending_activation_reports_recovery_without_selecting_a_packet(
    tmp_path, contents
):
    project, _, _ = _import_project.__wrapped__(tmp_path)
    workspace = TimelineWorkspace.from_project(project)
    marker = workspace.timeline_dir / "import-activation.pending.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(contents)
    before = _tree(tmp_path)
    status = workspace.status()["timelineImport"]
    assert status["status"] == "recovery-required"
    assert status["originRef"] is None
    assert status["recoveryRequired"] is True
    assert status["capabilityLevel"] is None
    assert status["pendingActivation"]["status"] == "invalid"
    assert status["blockers"][0]["code"] == "OTIO_RECOVERY_REQUIRED"
    assert len(json.dumps(status).encode()) < 16384
    assert _tree(tmp_path) == before


def test_valid_pending_activation_is_reported_separately_from_current_selection(
    tmp_path,
):
    service, _, revision = _active(tmp_path)
    origin = deepcopy(revision["snapshot"]["originRef"])
    service._pending_path().write_text(
        json.dumps(
            {"importId": origin["importId"], "operationId": origin["activationId"]}
        )
    )
    before = _tree(tmp_path)
    status = service.workspace.timeline_import_status()
    assert status["status"] == "recovery-required"
    assert status["compatibilityState"] == "verified-activation"
    assert status["originRef"] == origin
    assert status["pendingActivation"]["status"] == "pending"
    assert status["pendingActivation"]["importId"] == origin["importId"]
    assert "Reconcile" in status["nextAction"]
    assert status["recoveryRequired"] is True
    assert _tree(tmp_path) == before


def test_valid_pending_marker_without_a_canonical_head_never_selects_its_packet(
    tmp_path,
):
    project, _, _ = _import_project.__wrapped__(tmp_path)
    workspace = TimelineWorkspace.from_project(project)
    marker = workspace.timeline_dir / "import-activation.pending.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"importId": "a" * 64, "operationId": "b" * 64}))
    before = _tree(tmp_path)
    status = workspace.timeline_import_status()
    assert status["status"] == "recovery-required"
    assert status["originRef"] is None
    assert status["capabilityLevel"] is None
    assert status["compatibilityState"] == "not-checked"
    assert status["pendingActivation"]["status"] == "pending"
    assert "packet" not in status
    assert _tree(tmp_path) == before
