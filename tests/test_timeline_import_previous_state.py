"""Activation evidence cannot erase a nonempty canonical previous selection."""

import json

import pytest

from avo.timeline.contracts import content_hash
from avo.timeline.import_evidence import verify_import_origin
from avo.timeline.otio_import import ImportError
from avo.timeline.store import write_immutable_json
from tests.test_timeline_import_evidence import _prepare_evidence
from tests.test_timeline_import_reimport import _commit, _replacement


def _erase_previous(path):
    intent = json.loads(path.read_text(encoding="utf-8"))
    intent["previousRevisionId"] = None
    intent["previousSnapshot"] = None
    path.write_text(json.dumps(intent), encoding="utf-8")
    return intent


def test_prepared_nonempty_activation_cannot_erase_its_previous_content(tmp_path):
    service, _, before, ready = _replacement(tmp_path)
    session = service.load(ready["importId"])
    intent = service._activation_intent(
        session,
        ready["validationHash"],
        before["contentHash"],
        "fixture-editor",
        "Prepared replacement fixture",
    )
    path = service.packet_path(
        ready["importId"], f"activation/{intent['operationId']}.json"
    )
    _erase_previous(path)
    count = len(service.workspace.store("cmap").load_index()["revisionRefs"])
    with pytest.raises(ImportError):
        _commit(service, ready, before["contentHash"])
    assert service.head_hash() == before["contentHash"]
    assert len(service.workspace.store("cmap").load_index()["revisionRefs"]) == count


def test_rehashed_completed_evidence_cannot_claim_empty_previous_canonical_state(
    tmp_path,
):
    service, _, before, ready = _replacement(tmp_path)
    revision = _commit(service, ready, before["contentHash"])["revision"]
    operation = revision["snapshot"]["originRef"]["activationId"]
    path = service.packet_path(ready["importId"], f"activation/{operation}.json")
    intent = _erase_previous(path)
    # A self-consistent evidence hash is insufficient when it contradicts the
    # immutable canonical parent. This is the result the earlier retry bug wrote.
    completed = {
        **intent,
        "phase": "reconciled",
        "revisionHash": revision["contentHash"],
    }
    result_path = service.packet_path(
        ready["importId"], f"activation-results/{content_hash(completed)}.json"
    )
    write_immutable_json(result_path, completed)
    with pytest.raises(ValueError, match="import evidence|Import evidence"):
        verify_import_origin(service.workspace, revision)
    assert revision["parentRevisionId"] == before["revisionId"]
    assert (
        service.workspace.store("cmap").revision(before["revisionId"])["snapshot"]
        == before["snapshot"]
    )


def test_postcommit_proposal_corruption_keeps_recovery_guard_until_exact_restore(
    tmp_path, monkeypatch
):
    # Synthetic media facts and fixture-only Sync; no creator approval is inferred.
    service, ready = _prepare_evidence(tmp_path)
    proposal = service.packet_path(
        ready["importId"], ready["session"]["refs"]["proposal"]["path"]
    )
    original = proposal.read_bytes()
    real_record = service._record

    def corrupt_after_result(import_id, category, value):
        result = real_record(import_id, category, value)
        if category == "activation-results":
            proposal.write_bytes(b"{}")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(service, "_record", corrupt_after_result)
        with pytest.raises(ImportError) as raised:
            _commit(service, ready, "empty")
    assert raised.value.code == "OTIO_RECOVERY_REQUIRED"
    assert service.head_hash() != "empty"
    assert service._pending_path().is_file()
    assert len(service.workspace.store("cmap").load_index()["revisionRefs"]) == 1
    proposal.write_bytes(original)
    recovered = _commit(service, ready, "empty")
    assert not service._pending_path().exists()
    assert len(service.workspace.store("cmap").load_index()["revisionRefs"]) == 1
    assert verify_import_origin(service.workspace, recovered["revision"])


def test_source_mutation_after_final_session_save_keeps_recovery_guard(
    tmp_path, monkeypatch
):
    from pathlib import Path

    service, ready = _prepare_evidence(tmp_path)
    source = Path(ready["proposal"]["snapshot"]["sources"][0]["locator"])
    original = source.read_bytes()
    real_save = service._save

    def mutate_after_save(session):
        result = real_save(session)
        if session["state"] == "active-draft":
            source.write_bytes(b"mutated after final import session bookkeeping")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(service, "_save", mutate_after_save)
        with pytest.raises(ImportError) as raised:
            _commit(service, ready, "empty")
    assert raised.value.code == "OTIO_RECOVERY_REQUIRED"
    assert service.head_hash() != "empty"
    assert service._pending_path().is_file()
    source.write_bytes(original)
    recovered = _commit(service, ready, "empty")
    assert not service._pending_path().exists()
    assert len(service.workspace.store("cmap").load_index()["revisionRefs"]) == 1
    assert verify_import_origin(service.workspace, recovered["revision"])


def test_dangling_pending_symlink_is_not_overwritten_or_removed(tmp_path):
    service, ready = _prepare_evidence(tmp_path)
    marker = service._pending_path()
    missing = tmp_path / "unavailable-pending-operation.json"
    try:
        marker.symlink_to(missing)
        original_link = marker.readlink()
    except OSError:
        pytest.skip("Native symlink creation is unavailable")
    assert marker.is_symlink() and not marker.exists()
    with pytest.raises(ImportError) as raised:
        _commit(service, ready, "empty")
    assert raised.value.code == "OTIO_RECOVERY_REQUIRED"
    assert service.head_hash() == "empty"
    assert marker.is_symlink() and not marker.exists()
    assert marker.readlink() == original_link
