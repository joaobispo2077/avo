from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from queue import Empty

import pytest

from avo.timeline import store as storage
from avo.timeline.store import ArtifactStore, StoreError


def _store(path):
    store = ArtifactStore(path)
    store.initialize(
        artifact_type="cmap",
        artifact_id="writer-test:cmap",
        video_id="writer-test",
        provider="neutral",
        timeline_domain="raw-source",
    )
    return store


def _append_child(
    path, ready, start, output, expect_empty, observed=None, release=None
):
    store = ArtifactStore(Path(path))
    if observed is not None:
        original_head_hash = store._head_hash

        def observe_head(index):
            result = original_head_hash(index)
            observed.set()
            if not release.wait(30):
                raise RuntimeError("postcompare release timed out")
            return result

        store._head_hash = observe_head
    ready.set()
    if not start.wait(30):
        output.put(("error", "start event timed out"))
        return
    try:
        kwargs = {"expected_head_hash": "empty"} if expect_empty else {}
        revision = store.append_revision(
            snapshot={}, actor="child-writer", reason="competing write", **kwargs
        )
    except StoreError as exc:
        output.put(("conflict", str(exc)))
    except Exception as exc:
        output.put(("error", f"{type(exc).__name__}: {exc}"))
    else:
        output.put(("written", revision["revisionId"]))


def _finish(processes, output):
    for process in processes:
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
    output.close()
    output.join_thread()


def _release_after_competing_reads(observed, release, output):
    early = []
    for _ in range(600):
        if all(event.is_set() for event in observed):
            break
        try:
            early.append(output.get(timeout=0.05))
        except Empty:
            continue
        break
    else:
        raise AssertionError("writers did not reach comparison or report conflict")
    release.set()
    return early


def test_explicit_expected_empty_succeeds_once_then_rejects(tmp_path):
    store = _store(tmp_path / "timeline/cmap.json")
    revision = store.append_revision(
        snapshot={}, actor="importer", reason="first import", expected_head_hash="empty"
    )
    assert store.head_hash() == revision["contentHash"]
    with pytest.raises(StoreError, match="compare-and-swap"):
        store.append_revision(
            snapshot={},
            actor="importer",
            reason="stale import",
            expected_head_hash="empty",
        )
    assert len(store.load_index()["revisionRefs"]) == 1


def test_omitted_and_none_expectation_keep_legacy_append_behavior(tmp_path):
    store = _store(tmp_path / "timeline/cmap.json")
    first = store.append_revision(snapshot={}, actor="editor", reason="first")
    second = store.append_revision(
        snapshot={}, actor="editor", reason="second", expected_head_hash=None
    )
    assert second["parentRevisionId"] == first["revisionId"]
    assert len(store.load_index()["revisionRefs"]) == 2


def test_two_process_expected_empty_race_has_one_winner(tmp_path):
    path = tmp_path / "timeline/cmap.json"
    store = _store(path)
    context = multiprocessing.get_context("spawn")
    start, release, output = context.Event(), context.Event(), context.Queue()
    ready = [context.Event(), context.Event()]
    observed = [context.Event(), context.Event()]
    processes = [
        context.Process(
            target=_append_child,
            args=(str(path), signal, start, output, True, comparison, release),
        )
        for signal, comparison in zip(ready, observed, strict=True)
    ]
    try:
        for process in processes:
            process.start()
        assert all(signal.wait(30) for signal in ready)
        start.set()
        results = _release_after_competing_reads(observed, release, output)
        results.extend(output.get(timeout=30) for _ in range(2 - len(results)))
    finally:
        start.set()
        release.set()
        _finish(processes, output)
    assert sorted(status for status, _ in results) == ["conflict", "written"]
    conflict = next(message for status, message in results if status == "conflict")
    assert "another writer" in conflict or "compare-and-swap" in conflict
    assert len(store.load_index()["revisionRefs"]) == 1
    with pytest.raises(StoreError, match="compare-and-swap"):
        store.append_revision(
            snapshot={},
            actor="retry",
            reason="stale empty retry",
            expected_head_hash="empty",
        )
    assert len(store.load_index()["revisionRefs"]) == 1


def test_importer_lock_rejects_an_ordinary_process_writer(tmp_path):
    path = tmp_path / "timeline/cmap.json"
    store = _store(path)
    context = multiprocessing.get_context("spawn")
    ready, start, output = context.Event(), context.Event(), context.Queue()
    process = context.Process(
        target=_append_child, args=(str(path), ready, start, output, False)
    )
    try:
        with storage.timeline_writer(path.parent):
            process.start()
            assert ready.wait(30)
            start.set()
            status, message = output.get(timeout=30)
            assert status == "conflict"
            assert "another writer" in message
            assert store.head_hash() is None
    finally:
        start.set()
        if process.pid is not None:
            _finish([process], output)
        else:
            output.close()
            output.join_thread()
    store.append_revision(snapshot={}, actor="editor", reason="after importer releases")
    assert len(store.load_index()["revisionRefs"]) == 1


def test_timeline_writer_is_reentrant_for_nested_store_mutation(tmp_path):
    path = tmp_path / "timeline/cmap.json"
    store = _store(path)
    with storage.timeline_writer(path.parent):
        with storage.timeline_writer(path.parent):
            revision = store.append_revision(
                snapshot={},
                actor="importer",
                reason="nested write",
                expected_head_hash="empty",
            )
    assert store.head_hash() == revision["contentHash"]
    assert len(store.load_index()["revisionRefs"]) == 1


def test_cleanup_never_unlinks_persistent_writer_coordination(tmp_path):
    from avo.project_inventory import PreservedSetResult, scan_delete_candidates

    timeline = tmp_path / "edit/timeline"
    with storage.timeline_writer(timeline):
        candidates, _ = scan_delete_candidates(
            tmp_path, PreservedSetResult([], None, [], [])
        )
        assert timeline / ".mutation.lock" not in candidates


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork qualification")
def test_forked_child_unwind_does_not_release_parent_lock(tmp_path):
    read_fd, write_fd = os.pipe()
    child = None
    with storage.timeline_writer(tmp_path / "timeline"):
        child = os.fork()
        if child:
            os.close(write_fd)
            try:
                assert os.read(read_fd, 64) == b"conflict"
            finally:
                os.close(read_fd)
                _, status = os.waitpid(child, 0)
            assert status == 0
    if child == 0:
        # Unwind the inherited context first, then try a new writer.
        try:
            with storage.timeline_writer(tmp_path / "timeline"):
                os.write(write_fd, b"acquired")
        except StoreError:
            os.write(write_fd, b"conflict")
        finally:
            os._exit(0)
