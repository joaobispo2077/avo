"""Library authority survives stale writers and orphan publications."""

import pytest

from avo.library.rules import LibraryError
from avo.library.store import LibraryStore


def test_immutable_roundtrip_and_tampering(tmp_path):
    store = LibraryStore(tmp_path, "example")
    ref = store.put("inventory", {"recordings": [], "summary": {}, "scope": {}})
    assert store.get(ref)["recordings"] == []
    store.path(ref["path"]).write_text("{}")
    with pytest.raises(LibraryError):
        store.get(ref)


def test_head_compare_and_swap_and_orphan(tmp_path):
    store = LibraryStore(tmp_path, "example")
    with store.exclusive():
        head = store.initialize()
        old = head["headHash"]
        ref = store.put("inventory", {"recordings": [], "summary": {}, "scope": {}})
        store.publish({**head, "inventoryRef": ref}, old)
        with pytest.raises(LibraryError):
            store.publish(head, old)
    assert store.head()["inventoryRef"] == ref
    store.put(
        "inventory", {"recordings": [], "summary": {"uncommitted": 1}, "scope": {}}
    )
    assert store.head()["inventoryRef"] == ref


def test_writer_lock_is_nonblocking(tmp_path):
    store = LibraryStore(tmp_path, "example")
    with store.exclusive():
        with pytest.raises(LibraryError, match="writer"):
            with LibraryStore(tmp_path, "example").exclusive():
                pytest.fail("two writers acquired the same lock")


def test_concurrent_status_reads_allow_atomic_head_publication(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = LibraryStore(tmp_path, "example")
    head = store.initialize()

    def reads():
        for _ in range(100):
            assert store.head()["libraryId"] == head["libraryId"]

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(reads)
        for _ in range(30):
            head = store.publish(head, head["headHash"])
        future.result()


def test_root_identity_and_unknown_head_fields_fail_closed(tmp_path):
    from avo.timeline.contracts import content_hash
    from avo.timeline.store import atomic_write_json

    store = LibraryStore(tmp_path, "example")
    head = store.initialize()
    body = {k: v for k, v in head.items() if k != "headHash"}
    body["rootIdentity"]["fileId"] += 1
    atomic_write_json(store.head_path, {**body, "headHash": content_hash(body)})
    with pytest.raises(LibraryError, match="identity"):
        store.head()
    with pytest.raises(LibraryError):
        store.publish({**head, "unexpected": True}, head["headHash"])
