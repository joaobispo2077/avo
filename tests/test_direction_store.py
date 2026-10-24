"""Direction publication behavior on real files; no provider or media fixtures."""

from __future__ import annotations

import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from avo.direction import store as direction_store
from avo.direction.rules import DirectionError
from avo.timeline.contracts import content_hash, document_hash_excluding


def document(identifier: str = "record-one", text: str = "Natural delivery") -> dict:
    """Untyped persistence fixture: domain schema tests are a separate boundary."""
    value = {
        "schemaVersion": "1.0.0",
        "documentType": "EvidenceRecord",
        "id": identifier,
        "createdAt": "2026-10-16T00:00:00Z",
        "createdBy": {"type": "native", "id": "avo.direction-test"},
        "summary": text,
    }
    value["documentHash"] = document_hash_excluding(value, "documentHash")
    return value


def reference(value: dict, path: str) -> dict:
    return {"id": value["id"], "documentHash": value["documentHash"], "path": path}


def index(value: dict | None = None, *, accepted: bool = False) -> dict:
    ref = reference(value, f"records/{value['id']}.json") if value else None
    return {
        "schemaVersion": "1.0.0",
        "documentType": "ProviderIndex",
        "provider": "example",
        "proposedRefs": [ref] if ref else [],
        "acceptedRef": ref if accepted else None,
        "decisionRefs": [],
    }


def publish(store, value: dict, *, request_id="request-one", expected="absent"):
    return store.publish(
        expected_index_hash=expected,
        request_id=request_id,
        documents=[(f"records/{value['id']}.json", value, None)],
        index=index(value),
    )


def write_lock(root: Path, *, pid: int, host: str | None = None) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    value = {"pid": pid, "host": host or socket.gethostname(), "token": "test-lock"}
    (root / ".write.lock").write_text(json.dumps(value), encoding="utf-8")
    return value


def test_missing_reads_do_not_create_a_direction_directory(tmp_path: Path) -> None:
    root = tmp_path / "provider" / "direction"
    store = direction_store.DirectionStore(root)
    assert store.load_index() is None
    assert store.index_hash() == "absent"
    with pytest.raises(DirectionError):
        store.load_document("records/not-present.json")
    assert not root.exists()


def test_immutable_write_returns_exact_reference_without_publishing(tmp_path: Path):
    store = direction_store.DirectionStore(tmp_path / "direction")
    value = document()
    path = "records/record-one.json"
    assert store.write_document(path, value) == reference(value, path)
    assert store.load_document(path) == value
    assert store.load_index() is None
    assert store.index_hash() == "absent"


def test_immutable_retry_cannot_overwrite_same_identity(tmp_path: Path) -> None:
    store = direction_store.DirectionStore(tmp_path)
    original = document()
    first = store.write_document("records/record-one.json", original)
    before = (tmp_path / "records/record-one.json").read_bytes()
    assert store.write_document("records/record-one.json", original) == first
    with pytest.raises(DirectionError):
        store.write_document("records/record-one.json", document(text="Different"))
    assert (tmp_path / "records/record-one.json").read_bytes() == before


def test_tampered_document_is_rejected_even_with_unchanged_size_and_mtime(
    tmp_path: Path,
) -> None:
    store = direction_store.DirectionStore(tmp_path)
    store.write_document("records/record-one.json", document(text="quiet"))
    path = tmp_path / "records/record-one.json"
    stat = path.stat()
    encoded = path.read_text(encoding="utf-8").replace("quiet", "quick")
    path.write_text(encoded, encoding="utf-8", newline="\n")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size
    with pytest.raises(DirectionError):
        store.load_document("records/record-one.json")


def test_wrong_supplied_document_hash_is_rejected_before_write(tmp_path: Path):
    store = direction_store.DirectionStore(tmp_path / "direction")
    value = {**document(), "documentHash": "0" * 64}
    with pytest.raises(DirectionError):
        store.write_document("records/record-one.json", value)
    assert not (tmp_path / "direction/records/record-one.json").exists()
    assert store.load_index() is None


def test_index_publication_is_hash_verified_and_does_not_accept_a_proposal(
    tmp_path: Path,
) -> None:
    store = direction_store.DirectionStore(tmp_path)
    result = publish(store, document())
    assert result == store.load_index()
    assert result["indexHash"] == document_hash_excluding(result, "indexHash")
    assert store.index_hash() == result["indexHash"]
    assert result["acceptedRef"] is None
    assert result["proposedRefs"] == [reference(document(), "records/record-one.json")]
    assert not (tmp_path / ".write.lock").exists()


def test_changed_index_bytes_do_not_keep_a_trusted_stored_hash(tmp_path: Path):
    store = direction_store.DirectionStore(tmp_path)
    publish(store, document())
    path = tmp_path / "index.json"
    altered = json.loads(path.read_text(encoding="utf-8"))
    altered["acceptedRef"] = altered["proposedRefs"][0]
    path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(DirectionError):
        store.load_index()


def test_stale_index_rejects_before_creating_new_immutable_bodies(tmp_path: Path):
    store = direction_store.DirectionStore(tmp_path)
    publish(store, document())
    before = (tmp_path / "index.json").read_bytes()
    with pytest.raises(DirectionError) as caught:
        publish(store, document("record-two"), request_id="request-two")
    assert caught.value.code == "DIR_INDEX_CONFLICT"
    assert (tmp_path / "index.json").read_bytes() == before
    assert not (tmp_path / "records/record-two.json").exists()


def test_identical_request_retry_is_idempotent_despite_old_expected_index(
    tmp_path: Path,
) -> None:
    store = direction_store.DirectionStore(tmp_path)
    first = publish(store, document())
    before = (tmp_path / "index.json").read_bytes()
    assert publish(store, document()) == first
    assert (tmp_path / "index.json").read_bytes() == before
    with pytest.raises(DirectionError):
        publish(store, document("record-two"), expected=store.index_hash())
    assert not (tmp_path / "records/record-two.json").exists()
    assert (tmp_path / "index.json").read_bytes() == before


def test_failure_before_index_publication_leaves_orphan_unselected_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = direction_store.DirectionStore(tmp_path)
    publish(store, document())
    before = (tmp_path / "index.json").read_bytes()
    expected = store.index_hash()
    second = document("record-two")
    original = direction_store.atomic_write_json

    def fail_index(path, value):
        if Path(path) == tmp_path / "index.json":
            raise OSError("simulated interruption before index replacement")
        return original(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(direction_store, "atomic_write_json", fail_index)
        with pytest.raises((OSError, DirectionError)):
            publish(store, second, request_id="request-two", expected=expected)
    assert (tmp_path / "index.json").read_bytes() == before
    assert store.load_index()["acceptedRef"] is None
    assert store.load_index()["proposedRefs"] == [
        reference(document(), "records/record-one.json")
    ]
    assert not (tmp_path / ".write.lock").exists()
    restored = publish(store, second, request_id="request-two", expected=expected)
    assert restored["proposedRefs"] == [reference(second, "records/record-two.json")]


def test_failed_non_authoritative_write_cannot_erase_published_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = direction_store.DirectionStore(tmp_path)
    publish(store, document())
    before = (tmp_path / "index.json").read_bytes()

    def fail_write(*_args, **_kwargs):
        raise OSError("derived artifact storage unavailable")

    monkeypatch.setattr(direction_store, "write_immutable_json", fail_write)
    with pytest.raises((OSError, DirectionError)):
        store.write_document("views/failed-view.json", document("derived-view"))
    assert (tmp_path / "index.json").read_bytes() == before
    assert store.load_index()["acceptedRef"] is None


def test_same_resource_writer_fails_while_first_writer_owns_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = direction_store.DirectionStore(tmp_path)
    entered = Event()
    release = Event()
    original = direction_store.write_immutable_json

    def hold_first_writer(path, value):
        if Path(path).name == "record-one.json":
            entered.set()
            assert release.wait(5), "test writer did not receive release"
        return original(path, value)

    monkeypatch.setattr(direction_store, "write_immutable_json", hold_first_writer)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(publish, store, document())
        try:
            assert entered.wait(5), "first writer never acquired its resource"
            second = pool.submit(
                publish, store, document("record-two"), request_id="request-two"
            )
            with pytest.raises(DirectionError) as caught:
                second.result(timeout=2)
            assert caught.value.code == "DIR_RESOURCE_BUSY"
        finally:
            release.set()
        first.result(timeout=5)
    assert not (tmp_path / "records/record-two.json").exists()


def test_different_resources_do_not_share_a_global_write_lock(tmp_path: Path):
    first_root = tmp_path / "first"
    write_lock(first_root, pid=os.getpid())
    second = direction_store.DirectionStore(tmp_path / "second")
    assert publish(second, document())["proposedRefs"]
    assert (first_root / ".write.lock").exists()


def test_existing_old_lock_is_not_stolen_by_age(tmp_path: Path) -> None:
    lock = write_lock(tmp_path, pid=os.getpid())
    lock_path = tmp_path / ".write.lock"
    os.utime(lock_path, (1, 1))
    store = direction_store.DirectionStore(tmp_path)
    with pytest.raises(DirectionError) as caught:
        publish(store, document())
    assert caught.value.code == "DIR_RESOURCE_BUSY"
    assert json.loads(lock_path.read_text(encoding="utf-8")) == lock
    assert not (tmp_path / "index.json").exists()


@pytest.mark.parametrize("authorized", [False, True])
def test_live_owner_lock_cannot_be_recovered(tmp_path: Path, authorized: bool):
    lock = write_lock(tmp_path, pid=os.getpid())
    store = direction_store.DirectionStore(tmp_path)
    with pytest.raises(DirectionError):
        store.recover_lock(expected_lock_hash=content_hash(lock), authorized=authorized)
    assert json.loads((tmp_path / ".write.lock").read_text(encoding="utf-8")) == lock


def test_recovery_rejects_wrong_identity_and_foreign_host(tmp_path: Path) -> None:
    lock = write_lock(tmp_path, pid=999999, host="a-different-host.invalid")
    store = direction_store.DirectionStore(tmp_path)
    for expected in ("0" * 64, content_hash(lock)):
        with pytest.raises(DirectionError):
            store.recover_lock(expected_lock_hash=expected, authorized=True)
    assert json.loads((tmp_path / ".write.lock").read_text(encoding="utf-8")) == lock


def test_unauthorized_recovery_does_not_create_an_absent_root(tmp_path: Path):
    root = tmp_path / "absent"
    store = direction_store.DirectionStore(root)
    with pytest.raises(DirectionError):
        store.recover_lock(expected_lock_hash="0" * 64, authorized=False)
    assert not root.exists()


@pytest.mark.parametrize("relative", ["../escape.json", "nested/../../escape.json"])
def test_traversal_write_and_read_are_rejected(tmp_path: Path, relative: str):
    store = direction_store.DirectionStore(tmp_path / "direction")
    with pytest.raises(DirectionError):
        store.write_document(relative, document())
    with pytest.raises(DirectionError):
        store.load_document(relative)
    assert not (tmp_path / "escape.json").exists()
    assert not (tmp_path / "index.json").exists()


def test_absolute_output_path_is_rejected_even_if_lexically_inside_root(
    tmp_path: Path,
) -> None:
    store = direction_store.DirectionStore(tmp_path)
    absolute = str(tmp_path / "records/record-one.json")
    with pytest.raises(DirectionError):
        store.write_document(absolute, document())
    assert not (tmp_path / "records/record-one.json").exists()


def test_symlink_escape_does_not_read_or_write_outside_root(tmp_path: Path):
    root = tmp_path / "direction"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    original = document()
    target = outside / "record-one.json"
    target.write_text(json.dumps(original), encoding="utf-8")
    before = target.read_bytes()
    try:
        (root / "records").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("host cannot create directory symlinks")
    store = direction_store.DirectionStore(root)
    with pytest.raises(DirectionError):
        store.load_document("records/record-one.json")
    with pytest.raises(DirectionError):
        store.write_document("records/record-one.json", document(text="Changed"))
    assert target.read_bytes() == before
