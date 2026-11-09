"""Durable-write and retry contracts; media/Sync evidence is fixture-only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline import import_service
from avo.timeline import store as storage
from avo.timeline.import_evidence import verify_import_origin
from avo.timeline.lifecycle import PipelineRunStore
from avo.timeline.otio_import import ImportError
from tests.test_timeline_import_evidence import _activate, _prepare_evidence
from tests.test_timeline_import_reimport import _commit, _replacement, _scoped_edit


def _count(service):
    path = service.workspace.artifact_path("cmap")
    return (
        len(service.workspace.store("cmap").load_index()["revisionRefs"])
        if path.exists()
        else 0
    )


@pytest.mark.parametrize(
    "boundary",
    [
        "before-export",
        "after-export",
        "before-snapshot",
        "after-snapshot",
        "before-index",
        "after-index",
    ],
)
def test_cancelled_preparation_can_retry_partial_packet_without_selecting_a_head(
    tmp_path, monkeypatch, boundary
):
    service, ready = _prepare_evidence(tmp_path)
    before = _activate(service, ready)
    session = service.load(ready["importId"])
    document = json.loads(
        (service.root / ready["importId"] / "source.otio").read_text()
    )
    document["name"] = "Interrupted preparation fixture"
    export = tmp_path / "interrupted-preparation.otio"
    export.write_text(json.dumps(document), encoding="utf-8")
    attribute = "_immutable_bytes" if "export" in boundary else "write_immutable_json"
    real_write = getattr(import_service, attribute)

    def interrupt(path, value):
        selected = (
            Path(path).name
            == {
                "export": "source.otio",
                "snapshot": "snapshot.json",
                "index": "index.json",
            }[boundary.split("-")[1]]
        )
        if selected and boundary.startswith("before"):
            raise OSError("fixture cancellation before packet write")
        result = real_write(path, value)
        if selected:
            raise OSError("fixture cancellation after packet write")
        return result

    def prepare():
        return service.prepare(
            export,
            media_roots=session["options"]["mediaRoots"],
            mappings=session["options"]["mappings"],
            declarations=session["options"]["declarations"],
            actor="fixture-editor",
            reason="Retry a cancelled preparation",
        )

    with monkeypatch.context() as patch:
        patch.setattr(import_service, attribute, interrupt)
        with pytest.raises((ImportError, OSError)):
            prepare()
    assert service.head_hash() == before["contentHash"]
    assert (
        service.workspace.store("cmap").revision(before["revisionId"])["snapshot"]
        == before["snapshot"]
    )
    storage.require_reconciled(service.workspace.timeline_dir)
    prepared = prepare()
    assert (
        service.read_ref(prepared["importId"], prepared["session"]["refs"]["export"])
        == export.read_bytes()
    )
    assert _count(service) == 1


@pytest.mark.parametrize(
    "boundary", ["before-intent", "after-intent", "before-pending", "after-pending"]
)
def test_precommit_evidence_failure_leaves_prior_state_usable_and_retry_exact(
    tmp_path, monkeypatch, boundary
):
    service, ready = _prepare_evidence(tmp_path)
    attribute = "write_immutable_json" if "intent" in boundary else "atomic_write_json"
    real_write = getattr(import_service, attribute)

    def interrupt(path, value):
        selected = (
            Path(path).parent.name == "activation"
            if "intent" in boundary
            else Path(path).name == "import-activation.pending.json"
        )
        if selected and boundary.startswith("before"):
            raise OSError("fixture interruption before durable evidence")
        result = real_write(path, value)
        if selected:
            raise OSError("fixture interruption after durable evidence")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(import_service, attribute, interrupt)
        with pytest.raises((ImportError, OSError)):
            _commit(service, ready, "empty")
    assert service.head_hash() == "empty"
    storage.require_reconciled(service.workspace.timeline_dir)
    result = _commit(service, ready, "empty")
    assert result["revision"]["snapshot"]["originRef"]["importId"] == ready["importId"]
    assert _count(service) == 1


@pytest.mark.parametrize("after_commit", [False, True])
def test_canonical_index_boundary_keeps_valid_old_or_new_state_and_retries_once(
    tmp_path, monkeypatch, after_commit
):
    service, ready = _prepare_evidence(tmp_path)
    index_path = service.workspace.artifact_path("cmap")
    real_write = storage.atomic_write_json

    def interrupt(path, value):
        selected = Path(path) == index_path and value.get("headRevisionId") is not None
        if selected and not after_commit:
            raise OSError("fixture interruption before canonical selection")
        result = real_write(path, value)
        if selected:
            raise OSError("fixture interruption after canonical selection")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(storage, "atomic_write_json", interrupt)
        with pytest.raises(ImportError):
            _commit(service, ready, "empty")
    # A committed index must never reference an unlinked immutable revision body.
    index = service.workspace.store("cmap").load_index()
    assert bool(index["headRevisionId"]) is after_commit
    if not after_commit:
        storage.require_reconciled(service.workspace.timeline_dir)
    else:
        with pytest.raises(storage.StoreError, match="RECOVERY_REQUIRED"):
            storage.require_reconciled(service.workspace.timeline_dir)
    result = _commit(service, ready, "empty")
    assert _count(service) == 1
    assert verify_import_origin(service.workspace, result["revision"])


@pytest.mark.parametrize("after_write", [False, True])
def test_revision_body_interruption_before_selection_keeps_prior_state_usable(
    tmp_path, monkeypatch, after_write
):
    service, ready = _prepare_evidence(tmp_path)
    real_write = storage.write_immutable_json

    def interrupt(path, value):
        selected = Path(path).name.startswith("cmap-import-")
        if selected and not after_write:
            raise OSError("fixture interruption before immutable revision")
        result = real_write(path, value)
        if selected:
            raise OSError("fixture interruption after immutable revision")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(storage, "write_immutable_json", interrupt)
        with pytest.raises(ImportError):
            _commit(service, ready, "empty")
    assert service.head_hash() == "empty"
    storage.require_reconciled(service.workspace.timeline_dir)
    result = _commit(service, ready, "empty")
    assert _count(service) == 1
    assert verify_import_origin(service.workspace, result["revision"])


@pytest.mark.parametrize("after_write", [False, True])
def test_reconciliation_result_write_can_retry_without_duplicate_canonical_commit(
    tmp_path, monkeypatch, after_write
):
    service, ready = _prepare_evidence(tmp_path)
    real_write = import_service.write_immutable_json

    def interrupt(path, value):
        selected = Path(path).parent.name == "activation-results"
        if selected and not after_write:
            raise OSError("fixture interruption before reconciliation record")
        result = real_write(path, value)
        if selected:
            raise OSError("fixture interruption after reconciliation record")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(import_service, "write_immutable_json", interrupt)
        with pytest.raises(ImportError):
            _commit(service, ready, "empty")
    assert _count(service) == 1
    with pytest.raises(storage.StoreError, match="RECOVERY_REQUIRED"):
        storage.require_reconciled(service.workspace.timeline_dir)
    result = _commit(service, ready, "empty")
    assert _count(service) == 1
    assert verify_import_origin(service.workspace, result["revision"])


@pytest.mark.parametrize("after_write", [False, True])
def test_lifecycle_durable_write_retry_does_not_replay_completed_transitions(
    tmp_path, monkeypatch, after_write
):
    service, ready = _prepare_evidence(tmp_path)
    real_write = PipelineRunStore._write

    def interrupt(run, document, **kwargs):
        selected = document["mainState"] == "cmap-draft"
        if selected and not after_write:
            raise OSError("fixture interruption before lifecycle draft state")
        result = real_write(run, document, **kwargs)
        if selected:
            raise OSError("fixture interruption after lifecycle draft state")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(PipelineRunStore, "_write", interrupt)
        with pytest.raises(ImportError):
            _commit(service, ready, "empty")
    run = PipelineRunStore(service.workspace.pipeline_run_path)
    history = run.load()["transitionHistory"]
    result = _commit(service, ready, "empty")
    completed = run.load()
    assert completed["mainState"] == "cmap-draft"
    assert completed["transitionHistory"][: len(history)] == history
    assert (
        sum(
            event["toMainState"] == "cmap-draft"
            for event in completed["transitionHistory"]
        )
        == 1
    )
    assert len({event["eventId"] for event in completed["transitionHistory"]}) == len(
        completed["transitionHistory"]
    )
    assert _count(service) == 1
    assert verify_import_origin(service.workspace, result["revision"])


def test_original_changed_after_canonical_commit_keeps_recovery_guard_until_restored(
    tmp_path, monkeypatch
):
    service, ready = _prepare_evidence(tmp_path)
    original = Path(ready["proposal"]["snapshot"]["sources"][0]["locator"])
    original_bytes = original.read_bytes()
    index_path = service.workspace.artifact_path("cmap")
    real_write = storage.atomic_write_json

    def mutate_after_selection(path, value):
        result = real_write(path, value)
        if Path(path) == index_path and value.get("headRevisionId") is not None:
            original.write_bytes(b"fixture source changed after canonical selection")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(storage, "atomic_write_json", mutate_after_selection)
        with pytest.raises(ImportError):
            _commit(service, ready, "empty")
    assert _count(service) == 1
    with pytest.raises(storage.StoreError, match="RECOVERY_REQUIRED"):
        storage.require_reconciled(service.workspace.timeline_dir)
    original.write_bytes(original_bytes)
    result = _commit(service, ready, "empty")
    assert _count(service) == 1
    assert verify_import_origin(service.workspace, result["revision"])


@pytest.mark.parametrize("after_save", [False, True])
def test_postcommit_session_failure_reconciles_without_duplicate_revision_or_lifecycle(
    tmp_path, monkeypatch, after_save
):
    service, ready = _prepare_evidence(tmp_path)
    real_save = service._save

    def interrupt(session):
        if session["state"] == "active-draft" and not after_save:
            raise OSError("fixture interruption before session reconciliation")
        result = real_save(session)
        if session["state"] == "active-draft":
            raise OSError("fixture interruption after session reconciliation")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(service, "_save", interrupt)
        with pytest.raises(ImportError):
            _commit(service, ready, "empty")
    assert _count(service) == 1
    history = PipelineRunStore(service.workspace.pipeline_run_path).load()[
        "transitionHistory"
    ]
    result = _commit(service, ready, "empty")
    assert _count(service) == 1
    assert (
        PipelineRunStore(service.workspace.pipeline_run_path).load()[
            "transitionHistory"
        ]
        == history
    )
    assert not service._pending_path().exists()
    assert verify_import_origin(service.workspace, result["revision"])


def test_historical_exact_activation_retry_uses_immutable_receipt_after_revalidation(
    tmp_path,
):
    service, ready = _prepare_evidence(tmp_path)
    revision = _activate(service, ready)
    latest = service.validate(ready["importId"])
    assert latest["validationHash"] != ready["validationHash"]
    latest_refs = service.load(ready["importId"])["refs"]
    result = _commit(service, ready, "empty")
    assert result["revision"]["revisionId"] == revision["revisionId"]
    assert service.load(ready["importId"])["refs"] == latest_refs
    assert service.head_hash() == revision["contentHash"]
    assert _count(service) == 1


def test_exact_activation_retry_after_scoped_edit_never_reselects_original_content(
    tmp_path,
):
    service, ready = _prepare_evidence(tmp_path)
    revision = _activate(service, ready)
    later = _scoped_edit(service, revision)
    _commit(service, ready, "empty")
    assert service.head_hash() == later["contentHash"]
    assert _count(service) == 2
    assert verify_import_origin(service.workspace, later)


def test_committed_replacement_replays_interrupted_descendant_invalidation(
    tmp_path, monkeypatch
):
    service, _, before, ready = _replacement(tmp_path)
    bmap = service.workspace.store("bmap")
    bmap.append_revision(snapshot={}, actor="fixture", reason="Fixture-only descendant")
    real_invalidate = service.workspace.invalidate_descendants

    def interrupt(*args, **kwargs):
        raise OSError("fixture interruption before descendant invalidation")

    with monkeypatch.context() as patch:
        patch.setattr(service.workspace, "invalidate_descendants", interrupt)
        with pytest.raises(ImportError):
            _commit(service, ready, before["contentHash"])
    assert service.head_hash() != before["contentHash"]
    assert bmap.load_index()["activeState"] == "valid"
    assert service.workspace.invalidate_descendants == real_invalidate
    _commit(service, ready, before["contentHash"])
    assert bmap.load_index()["activeState"] == "stale"
    assert _count(service) == 3


def test_another_pending_operation_cannot_be_replaced_or_cleared(tmp_path):
    service, ready = _prepare_evidence(tmp_path)
    pending = {"importId": "a" * 64, "operationId": "b" * 64}
    storage.atomic_write_json(service._pending_path(), pending)
    with pytest.raises(ImportError, match="reconcil|activation"):
        _commit(service, ready, "empty")
    assert json.loads(service._pending_path().read_text()) == pending
    assert service.head_hash() == "empty"


def test_changed_original_between_validation_and_commit_keeps_prior_head(tmp_path):
    service, _, before, ready = _replacement(tmp_path)
    original = Path(before["snapshot"]["sources"][0]["locator"])
    original.write_bytes(b"changed after explicit validation")
    with pytest.raises(ImportError):
        _commit(service, ready, before["contentHash"])
    assert service.head_hash() == before["contentHash"]
    assert _count(service) == 2


def test_padded_activation_actor_and_reason_use_canonical_text_and_retry_once(tmp_path):
    service, ready = _prepare_evidence(tmp_path)
    options = {
        "validation_hash": ready["validationHash"],
        "expected_head": "empty",
        "actor": "  fixture-editor  ",
        "reason": "  Continue imported fixture  ",
    }
    result = service.activate(ready["importId"], **options)
    revision = result["revision"]
    assert revision["actor"] == "fixture-editor"
    assert revision["reason"] == "Continue imported fixture"
    assert (
        service.activate(ready["importId"], **options)["revision"]["revisionId"]
        == revision["revisionId"]
    )
    assert _count(service) == 1
    assert not service._pending_path().exists()
    assert verify_import_origin(service.workspace, revision)


def test_padded_return_actor_and_reason_use_canonical_text_and_retry_once(tmp_path):
    service, _, before, ready = _replacement(tmp_path, scoped=False)
    replacement = _commit(service, ready, before["contentHash"])["revision"]
    activation_id = replacement["snapshot"]["originRef"]["activationId"]
    options = {
        "expected_head": replacement["contentHash"],
        "actor": "  fixture-editor  ",
        "reason": "  Return fixture content  ",
    }
    result = service.rollback(activation_id, **options)
    revision = result["revision"]
    assert revision["actor"] == "fixture-editor"
    assert revision["reason"] == "Return fixture content"
    assert (
        service.rollback(activation_id, **options)["revision"]["revisionId"]
        == revision["revisionId"]
    )
    assert _count(service) == 3
    assert not service._pending_path().exists()
    assert verify_import_origin(service.workspace, revision)


@pytest.mark.parametrize("operation", ["activate", "return"])
def test_legacy_padded_committed_intent_recovers_without_rewriting_evidence(
    tmp_path, monkeypatch, operation
):
    if operation == "activate":
        service, ready = _prepare_evidence(tmp_path)
        attribute, fail_state = "_activation_intent", "active-draft"

        def perform():
            return _commit(service, ready, "empty")

    else:
        service, _, before, ready = _replacement(tmp_path, scoped=False)
        replacement = _commit(service, ready, before["contentHash"])["revision"]
        activation_id = replacement["snapshot"]["originRef"]["activationId"]
        attribute, fail_state = "_return_intent", "superseded"

        def perform():
            return service.rollback(
                activation_id,
                expected_head=replacement["contentHash"],
                actor="fixture-editor",
                reason="Recover legacy fixture",
            )

    count = _count(service)
    real_intent, real_save = getattr(service, attribute), service._save

    def legacy_intent(*args):
        return real_intent(*args[:-2], "  legacy-editor  ", "  Legacy fixture note  ")

    def interrupt(session):
        if session["state"] == fail_state:
            raise OSError("fixture interruption after canonical selection")
        return real_save(session)

    with monkeypatch.context() as patch:
        patch.setattr(service, attribute, legacy_intent)
        patch.setattr(service, "_save", interrupt)
        with pytest.raises(ImportError):
            perform()
    assert _count(service) == count + 1
    assert service._pending_path().exists()
    revision = perform()["revision"]
    assert revision["actor"] == "legacy-editor"
    assert revision["reason"] == "Legacy fixture note"
    assert _count(service) == count + 1
    assert not service._pending_path().exists()
    assert verify_import_origin(service.workspace, revision)
    assert perform()["revision"]["revisionId"] == revision["revisionId"]
    assert _count(service) == count + 1
