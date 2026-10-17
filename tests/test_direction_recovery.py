"""Adversarial publication boundaries and explicit local lock recovery."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

import pytest

from avo.direction import store as direction_store
from avo.direction.rules import DirectionError
from avo.timeline.contracts import content_hash
from tests.test_direction_store import document, index, publish, write_lock

LIMIT = 2 * 1024 * 1024


def serialized(value: dict) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def sized_document(size: int) -> dict:
    base = document(text="")
    return document(text="x" * (size - len(serialized(base))))


def test_old_request_retry_returns_original_result_without_reverting_current_index(
    tmp_path,
):
    store = direction_store.DirectionStore(tmp_path)
    first = publish(store, document())
    second = publish(
        store,
        document("record-two"),
        request_id="request-two",
        expected=store.index_hash(),
    )
    before = (tmp_path / "index.json").read_bytes()
    assert publish(store, document()) == first
    assert store.load_index() == second
    assert (tmp_path / "index.json").read_bytes() == before


def test_document_at_serialized_byte_budget_can_be_read_back(tmp_path):
    store = direction_store.DirectionStore(tmp_path)
    value = sized_document(LIMIT)
    assert len(serialized(value)) == LIMIT
    store.write_document("records/boundary.json", value)
    assert (tmp_path / "records/boundary.json").stat().st_size == LIMIT
    assert store.load_document("records/boundary.json") == value


def test_document_over_serialized_byte_budget_is_rejected_before_write(tmp_path):
    store = direction_store.DirectionStore(tmp_path)
    value = sized_document(LIMIT + 1)
    assert len(serialized(value)) == LIMIT + 1
    with pytest.raises(DirectionError):
        store.write_document("records/too-large.json", value)
    assert not (tmp_path / "records/too-large.json").exists()


def test_oversize_index_cannot_replace_authority_or_leave_new_sidecars(tmp_path):
    store = direction_store.DirectionStore(tmp_path)
    publish(store, document())
    before = (tmp_path / "index.json").read_bytes()
    value = document("record-two")
    enlarged = {**index(value), "profiles": {"x" * LIMIT: {}}}
    with pytest.raises(DirectionError):
        store.publish(
            expected_index_hash=store.index_hash(),
            request_id="oversize-index",
            documents=[("records/record-two.json", value, None)],
            index=enlarged,
        )
    assert (tmp_path / "index.json").read_bytes() == before
    assert not (tmp_path / "records/record-two.json").exists()


@pytest.mark.parametrize("relative", ["C:relative.json", "records/value.json:stream"])
def test_windows_drive_relative_and_alternate_stream_paths_are_refused(
    tmp_path, relative
):
    store = direction_store.DirectionStore(tmp_path)
    with pytest.raises(DirectionError):
        store.write_document(relative, document())
    with pytest.raises(DirectionError):
        store.load_document(relative)
    assert not (tmp_path / "index.json").exists()


def test_explicit_recovery_of_provably_exited_owner_keeps_orphan_inactive(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        check=True,
        capture_output=True,
        text=True,
    )
    departed_pid = int(completed.stdout.strip())
    assert departed_pid != os.getpid()
    store = direction_store.DirectionStore(tmp_path)
    store.write_document("records/orphan.json", document("orphan"))
    lock = write_lock(tmp_path, pid=departed_pid)
    digest = content_hash(lock)
    with pytest.raises(DirectionError):
        store.recover_lock(expected_lock_hash=digest, authorized=False)
    assert (tmp_path / ".write.lock").exists()
    result = store.recover_lock(expected_lock_hash=digest, authorized=True)
    assert result["recoveredLockHash"] == digest
    assert not (tmp_path / ".write.lock").exists()
    assert store.load_index() is None
    assert store.load_document("records/orphan.json")["id"] == "orphan"


def test_unprovable_owner_absence_does_not_allow_recovery(tmp_path, monkeypatch):
    lock = write_lock(tmp_path, pid=12345)

    def permission_denied(_pid):
        raise PermissionError("Cannot query this recorded owner")

    monkeypatch.setattr(direction_store, "_owner_absent", permission_denied)
    store = direction_store.DirectionStore(tmp_path)
    with pytest.raises(DirectionError):
        store.recover_lock(expected_lock_hash=content_hash(lock), authorized=True)
    assert json.loads((tmp_path / ".write.lock").read_text(encoding="utf-8")) == lock


def test_lock_replaced_during_owner_check_is_never_removed(tmp_path, monkeypatch):
    lock = write_lock(tmp_path, pid=12345)
    replacement = {"pid": os.getpid(), "host": socket.gethostname(), "token": "new"}

    def replaced_owner(_pid):
        (tmp_path / ".write.lock").write_text(json.dumps(replacement), encoding="utf-8")
        return True

    monkeypatch.setattr(direction_store, "_owner_absent", replaced_owner)
    store = direction_store.DirectionStore(tmp_path)
    with pytest.raises(DirectionError):
        store.recover_lock(expected_lock_hash=content_hash(lock), authorized=True)
    assert (
        json.loads((tmp_path / ".write.lock").read_text(encoding="utf-8"))
        == replacement
    )


@pytest.mark.parametrize("pid", [0, -1, True, "12345", None])
def test_invalid_owner_identity_is_not_treated_as_a_dead_process(tmp_path, pid):
    lock = write_lock(tmp_path, pid=pid)
    store = direction_store.DirectionStore(tmp_path)
    with pytest.raises(DirectionError):
        store.recover_lock(expected_lock_hash=content_hash(lock), authorized=True)
    assert (tmp_path / ".write.lock").exists()
