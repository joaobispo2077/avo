"""Immutable library bodies and a small head published after dependencies."""

from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from avo.library.rules import LibraryError, read_request, reject, safe_path, validate
from avo.timeline.contracts import content_hash
from avo.timeline.store import atomic_write_json, now_iso, write_immutable_json

BUCKETS = {
    "inventory": "inventory",
    "proposal": "proposals",
    "prepared": "prepared",
    "decision": "decisions",
    "operation": "operations",
    "event": "operations/events",
    "report": "reports",
    "handoff": "handoffs",
    "usage": "batches/usage",
}


def publish_json(path, value):
    """Retry only transient Windows sharing failures; never truncate in place."""
    for attempt in range(10):
        try:
            return atomic_write_json(path, value)
        except PermissionError as exc:
            if (
                os.name != "nt"
                or getattr(exc, "winerror", None) not in {5, 32}
                or attempt == 9
            ):
                raise
            time.sleep(0.01 * (attempt + 1))


class LibraryStore:
    def __init__(self, root, provider):
        self.root = Path(root).absolute()
        self.provider = provider
        self.created_bytes = 0
        self.head_path = safe_path(self.root, "edit/library-index.json")

    def path(self, relative):
        return safe_path(self.root, relative)

    @contextmanager
    def exclusive(self):
        path = self.path("edit/library/.mutation.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            try:
                if os.name == "nt":
                    import msvcrt

                    if stream.seek(0, 2) == 0:
                        stream.write(b"\0")
                        stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise LibraryError(
                    "LIB_RESOURCE_BUSY", "Library has another writer", status="conflict"
                ) from exc
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def initialize(self):
        if self.head_path.exists():
            return self.head()
        head = {
            "schemaVersion": 1,
            "libraryId": uuid4().hex,
            "root": str(self.root),
            "rootIdentity": self.root_identity(),
            "provider": self.provider,
            "inventoryRef": None,
            "proposalRef": None,
            "activeOperation": None,
            "updatedAt": now_iso(),
        }
        return self.publish(head, None)

    def head(self):
        head = read_request(self.head_path, limit=1024 * 1024)
        validate("head", head)
        body = {k: v for k, v in head.items() if k != "headHash"}
        if content_hash(body) != head.get("headHash"):
            reject("LIB_SOURCE_CHANGED", "Library head integrity failed", "stale")
        if head.get("root") != str(self.root) or head.get("provider") != self.provider:
            reject("LIB_INVALID_REQUEST", "Library root/provider binding differs")
        if head.get("rootIdentity", self.root_identity()) != self.root_identity():
            reject(
                "LIB_ROOT_UNSAFE",
                "Library root identity changed; explicit adoption is required",
            )
        return head

    def root_identity(self):
        info = self.root.stat()
        return {"device": info.st_dev, "fileId": info.st_ino}

    def publish(self, head, expected):
        current = self.head()["headHash"] if self.head_path.exists() else None
        if current != expected:
            reject("LIB_STALE_PROPOSAL", "Library head changed", "stale")
        body = {k: v for k, v in head.items() if k != "headHash"}
        body["updatedAt"] = now_iso()
        result = {**body, "headHash": content_hash(body)}
        validate("head", result)
        publish_json(self.head_path, result)
        self.created_bytes += self.head_path.stat().st_size
        return result

    def put(self, kind, body):
        validate(kind, body)
        digest = content_hash(body)
        bucket = BUCKETS[kind]
        relative = f"edit/library/{bucket}/{digest}.json"
        path = self.path(relative)
        existed = path.exists()
        write_immutable_json(
            path,
            {"schemaVersion": 1, "kind": kind, "body": body, "documentHash": digest},
        )
        if not existed:
            self.created_bytes += path.stat().st_size
        return {"id": digest, "path": relative, "sha256": digest}

    def get(self, ref):
        document = read_request(self.path(ref["path"]), limit=32 * 1024 * 1024)
        body = document.get("body")
        digest = content_hash(body)
        if digest != ref.get("sha256") or digest != document.get("documentHash"):
            reject("LIB_SOURCE_CHANGED", "Library document integrity failed", "stale")
        validate(document.get("kind"), body)
        return body

    def lookup(self, kind, identifier):
        identifier = identifier.split("@")[0]
        if not re.fullmatch("[a-f0-9]{64}", identifier):
            reject("LIB_INVALID_REQUEST", "Expected a returned document ID")
        ref = {
            "id": identifier,
            "path": f"edit/library/{BUCKETS[kind]}/{identifier}.json",
            "sha256": identifier,
        }
        return ref, self.get(ref)

    def cancel(self, operation_id):
        if not re.fullmatch("[a-f0-9]{32}", operation_id):
            reject("LIB_INVALID_REQUEST", "Invalid operation identity")
        path = self.path(f"edit/library/control/{operation_id}.cancel.json")
        publish_json(path, {"operationId": operation_id, "requestedAt": now_iso()})
        return {"operationId": operation_id, "status": "cancelling"}

    def cancelled(self, operation_id):
        return self.path(f"edit/library/control/{operation_id}.cancel.json").exists()
