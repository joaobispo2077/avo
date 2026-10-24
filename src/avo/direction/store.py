"""Small immutable direction documents and index-last publication."""

from __future__ import annotations

import json
import os
import re
import socket
import sys
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from avo.direction.rules import DirectionError
from avo.timeline.contracts import (
    content_hash,
    document_hash_excluding,
    validate_document,
)
from avo.timeline.store import StoreError, atomic_write_json, write_immutable_json

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


def _verify_hash(value, field):
    digest = value.get(field)
    if not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest):
        raise DirectionError("DIR_INVALID_REFERENCE", f"Missing exact {field}")
    if document_hash_excluding(value, field) != digest:
        raise DirectionError(
            "DIR_SOURCE_CHANGED", f"{field} does not match content", status="stale"
        )


def _read_json(path):
    try:
        with path.open("rb") as stream:
            encoded = stream.read(MAX_DOCUMENT_BYTES + 1)
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise DirectionError("DIR_INVALID_REFERENCE", "Document exceeds 2 MiB")
        value = json.loads(encoded, parse_constant=_reject_constant)
    except (OSError, ValueError) as exc:
        if isinstance(exc, DirectionError):
            raise
        raise DirectionError(
            "DIR_INVALID_REFERENCE", f"Cannot read document: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise DirectionError("DIR_INVALID_REFERENCE", "Document must be an object")
    return value


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def _owner_absent(pid):
    if sys.platform == "win32":
        # Query only. os.kill is not a safe Windows liveness probe.
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        query = kernel.OpenProcess
        query.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        query.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        handle = query(0x1000, False, pid)
        if handle:
            close(handle)
            return False
        if ctypes.get_last_error() == 87:
            return True
        raise OSError("Cannot query recorded process owner")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


class DirectionStore:
    """One resource-local immutable store; reads have no side effects."""

    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    def _path(self, relative):
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Expected a relative POSIX path"
            )
        candidate = Path(relative)
        if (
            candidate.is_absolute()
            or PureWindowsPath(relative).drive
            or ":" in relative
        ):
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Absolute paths are forbidden"
            )
        path = (self.root / candidate).resolve()
        if ".." in candidate.parts or not path.is_relative_to(self.root):
            raise DirectionError("DIR_INVALID_REFERENCE", "Path escapes direction root")
        return path

    def load_document(self, relative, schema_ref=None):
        value = _read_json(self._path(relative))
        _verify_hash(value, "documentHash")
        if schema_ref:
            validate_document(value, schema_ref)
        return value

    def write_document(self, relative, document, schema_ref=None):
        path = self._path(relative)
        if path.name in {"index.json", ".write.lock"}:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Authority files require publish"
            )
        _verify_hash(document, "documentHash")
        if schema_ref:
            validate_document(document, schema_ref)
        self._check_size(document)
        try:
            write_immutable_json(path, document)
        except StoreError as exc:
            raise DirectionError(
                "DIR_INDEX_CONFLICT", str(exc), status="conflict"
            ) from exc
        return {
            "id": document["id"],
            "documentHash": document["documentHash"],
            "path": relative,
        }

    def load_index(self):
        path = self._path("index.json")
        if not path.exists():
            return None
        value = _read_json(path)
        _verify_hash(value, "indexHash")
        self._validate_index(value)
        return value

    def index_hash(self):
        index = self.load_index()
        return index["indexHash"] if index else "absent"

    def request_result(self, request_id):
        """Read a committed retry snapshot without moving current authority."""
        current = self.load_index()
        recorded = (current or {}).get("requests", {}).get(request_id)
        if recorded is None:
            return None
        return self._original_result(current, request_id, recorded)

    @staticmethod
    def _validate_index(index):
        names = {
            "ProviderIndex": "avo.direction.schema.json",
            "ProjectBriefIndex": "avo.briefstart.schema.json",
        }
        kind = index.get("documentType")
        if kind not in names:
            raise DirectionError("DIR_INVALID_REFERENCE", "Unknown index type")
        validate_document(index, names[kind] + "#/$defs/" + kind)

    @contextmanager
    def _exclusive(self):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(".write.lock")
        record = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "token": uuid4().hex,
        }
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise DirectionError(
                "DIR_RESOURCE_BUSY", "Resource already has a writer", status="conflict"
            ) from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            yield
        finally:
            # Do not remove a replaced lock owned by somebody else.
            if path.exists() and _read_json(path) == record:
                path.unlink()

    @staticmethod
    def _check_size(value):
        encoded = (
            json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise DirectionError("DIR_INVALID_REFERENCE", "Document exceeds 2 MiB")

    def _validate_inputs(self, documents):
        for relative, document, schema_ref in documents:
            self._path(relative)
            _verify_hash(document, "documentHash")
            self._check_size(document)
            if schema_ref:
                validate_document(document, schema_ref)

    def _request_path(self, request_id):
        return self._path("requests/" + content_hash(request_id) + ".json")

    def _original_result(self, current, request_id, request_hash):
        if current["requests"][request_id] != request_hash:
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "Request ID reused with different content",
                status="conflict",
            )
        path = self._request_path(request_id)
        if not path.exists() and current.get("lastRequestId") == request_id:
            return current
        result = _read_json(path)
        _verify_hash(result, "indexHash")
        self._validate_index(result)
        if (
            result.get("lastRequestId") != request_id
            or result.get("lastRequestHash") != request_hash
        ):
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "Request result identity changed",
                status="conflict",
            )
        return result

    def _publish_new(self, index, current, request_id, request_hash, documents):
        requests = dict((current or {}).get("requests") or {})
        requests[request_id] = request_hash
        published = {
            **index,
            "requests": requests,
            "lastRequestId": request_id,
            "lastRequestHash": request_hash,
        }
        published["indexHash"] = document_hash_excluding(published, "indexHash")
        self._check_size(published)
        self._validate_index(published)
        for relative, document, schema_ref in documents:
            self.write_document(relative, document, schema_ref)
        # A result is reusable only if the authoritative index records its request.
        write_immutable_json(self._request_path(request_id), published)
        atomic_write_json(self._path("index.json"), published)
        return published

    def publish(self, *, expected_index_hash, request_id, documents, index):
        if not isinstance(request_id, str) or not request_id.strip():
            raise DirectionError("DIR_INVALID_REFERENCE", "request_id is required")
        self._validate_inputs(documents)
        ignored = {"indexHash", "requests", "lastRequestId", "lastRequestHash"}
        request_hash = content_hash(
            {
                "expectedIndexHash": expected_index_hash,
                "documents": documents,
                "index": {k: v for k, v in index.items() if k not in ignored},
            }
        )
        with self._exclusive():
            current = self.load_index()
            if request_id in (current or {}).get("requests", {}):
                return self._original_result(current, request_id, request_hash)
            actual = current["indexHash"] if current else "absent"
            if actual != expected_index_hash:
                raise DirectionError(
                    "DIR_INDEX_CONFLICT",
                    "Index changed",
                    status="conflict",
                    details={"currentIndexHash": actual},
                )
            return self._publish_new(
                index, current, request_id, request_hash, documents
            )

    def recover_lock(self, *, expected_lock_hash, authorized):
        if not authorized:
            raise DirectionError(
                "DIR_APPROVAL_SCOPE", "Explicit lock recovery authorization required"
            )
        path = self._path(".write.lock")
        record = _read_json(path)
        if (
            content_hash(record) != expected_lock_hash
            or record.get("host") != socket.gethostname()
        ):
            raise DirectionError(
                "DIR_RESOURCE_BUSY",
                "Lock identity/host cannot be verified",
                status="conflict",
            )
        pid = record.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise DirectionError(
                "DIR_RESOURCE_BUSY", "Owner identity is unknown", status="conflict"
            )
        try:
            absent = _owner_absent(pid)
        except OSError as exc:
            raise DirectionError(
                "DIR_RESOURCE_BUSY", "Owner absence cannot be proved", status="conflict"
            ) from exc
        if not absent:
            raise DirectionError(
                "DIR_RESOURCE_BUSY", "Recorded owner is still alive", status="conflict"
            )
        if _read_json(path) != record:
            raise DirectionError(
                "DIR_RESOURCE_BUSY", "Lock changed during recovery", status="conflict"
            )
        path.unlink()
        return {"status": "ok", "recoveredLockHash": expected_lock_hash}
