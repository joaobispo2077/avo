"""Exact import evidence closure for canonical reconstruction and cleanup."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from .contracts import (
    content_hash,
    file_fingerprint,
    fingerprint_stage,
    validate_document,
)
from .import_evidence import verify_import_origin
from .lineage import LineageError
from .otio_import import packet_identity, parse_export_bytes

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 10_000
MAX_PACKETS = 1_000
MAX_REVISIONS = 10_000
_SCHEMA = "avo.timeline-import.schema.json"
_SEMANTIC_DIRECTORIES = {
    "proposals",
    "validations",
    "activation-results",
    "return-results",
}


def _require(condition, detail):
    if not condition:
        raise LineageError(f"Cannot retain timeline import evidence: {detail}")


def _identifier(value):
    _require(
        isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value),
        "invalid import operation identity",
    )
    return value


def _contained(root, relative):
    value = Path(relative)
    _require(not value.is_absolute(), "evidence path must be packet-relative")
    result = (root / value).resolve()
    _require(
        result != root and result.is_relative_to(root),
        "evidence path escapes its contained root",
    )
    _require(
        result == root / value,
        "generated evidence path aliases its retained location; restore direct packet files",
    )
    return result


class _Retention:
    def __init__(self, workspace):
        self.workspace = workspace
        self.timeline = workspace.timeline_dir.resolve()
        raw = workspace.raw_dir.resolve()
        _require(
            self.timeline.is_relative_to(raw / "edit"),
            "canonical root escapes declared project edit directory",
        )
        self.root = (self.timeline / "imports").resolve()
        _require(
            self.root.is_relative_to(self.timeline),
            "imports root escapes canonical directory",
        )
        self.paths, self.data, self.packets, self.visiting = set(), {}, {}, set()
        self.total = 0
        self.revisions = {}
        self.index = None
        self.revision_refs = {}

    def _read(self, path):
        path = Path(path).resolve()
        _require(
            path.is_relative_to(self.timeline),
            "evidence path escapes canonical directory",
        )
        if path in self.data:
            return self.data[path]
        _require(
            len(self.data) < MAX_FILES, "evidence file count exceeds retention limit"
        )
        remaining = min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - self.total)
        _require(
            path.stat().st_size <= remaining,
            f"evidence exceeds retention byte budget: {path}",
        )
        with path.open("rb") as stream:
            data = stream.read(remaining + 1)
        _require(
            len(data) <= remaining,
            "evidence exceeds retention byte budget",
        )
        actual = file_fingerprint(path)
        _require(
            actual["sha256"] == hashlib.sha256(data).hexdigest()
            and actual["sizeBytes"] == len(data),
            f"evidence bytes changed while reading: {path}",
        )
        self.total += len(data)
        self.data[path] = data
        return data

    def _keep(self, path):
        path = Path(path).resolve()
        self._read(path)
        self.paths.add(path)
        return path

    def _document(self, path, schema=None, semantic=None, *, keep=True):
        data = self._read(path)
        parse_export_bytes(data)
        value = json.loads(data)
        if schema is not None:
            validate_document(value, schema)
        if semantic is not None:
            _require(
                content_hash(value) == semantic,
                f"semantic evidence hash differs: {path}",
            )
        if keep:
            self.paths.add(Path(path).resolve())
        return value

    def _reference(self, packet, reference):
        path = _contained(packet, reference["path"])
        data = self._read(path)
        _require(
            hashlib.sha256(data).hexdigest() == reference["sha256"],
            f"file-byte fingerprint differs: {path}",
        )
        _require(
            reference.get("sizeBytes", len(data)) == len(data),
            f"evidence byte size differs: {path}",
        )
        if path.suffix == ".json":
            semantic = path.stem if path.parent.name in _SEMANTIC_DIRECTORIES else None
            self._document(path, semantic=semantic)
        return self._keep(path)

    def _session_identity(self, value, import_id):
        workspace = self.workspace
        _require(
            (value["provider"], value["videoId"])
            == (str(workspace.project.get("provider") or ""), workspace.video_id),
            "packet target identity differs",
        )
        source = value["source"]
        expected = packet_identity(
            source["sha256"],
            source["timelinePointer"],
            value["provider"],
            value["videoId"],
            value["options"],
            normalizer_version=value["normalizerVersion"],
        )
        _require(
            value["importId"] == import_id == expected, "packet identity hash differs"
        )
        _require(
            value.get("supersedesImportId")
            == value["options"].get("supersedesImportId"),
            "packet predecessor identity differs",
        )
        _require(
            {"export", "snapshot"} <= value["refs"].keys(),
            "packet lacks original export or snapshot",
        )

    def _packet(self, import_id):
        import_id = _identifier(import_id)
        if import_id in self.packets:
            return self.packets[import_id]
        _require(import_id not in self.visiting, "packet predecessor cycle")
        _require(
            len(self.visiting) + len(self.packets) < MAX_PACKETS,
            "packet count exceeds retention limit",
        )
        self.visiting.add(import_id)
        packet = _contained(self.root, import_id)
        session = self._document(
            _contained(packet, "index.json"), _SCHEMA + "#/$defs/session"
        )
        self._session_identity(session, import_id)
        for reference in session["refs"].values():
            self._reference(packet, reference)
        self._original_packet(packet, session)
        previous = session["options"].get("supersedesImportId")
        if previous is not None:
            predecessor = self._packet(previous)
            _require(
                predecessor["source"] == session["source"],
                "repair predecessor has a different exact export/selection",
            )
        self.visiting.remove(import_id)
        self.packets[import_id] = session
        return session

    def _original_packet(self, packet, session):
        export = session["refs"]["export"]
        _require(
            export["path"] == "source.otio"
            and session["refs"]["snapshot"]["path"] == "snapshot.json",
            "packet original evidence paths differ",
        )
        _require(
            all(
                export[key] == session["source"][key] for key in ("sha256", "sizeBytes")
            ),
            "original export fingerprint differs from packet identity",
        )
        snapshot = self._document(
            packet / "snapshot.json", _SCHEMA + "#/$defs/snapshot"
        )
        _require(
            snapshot["source"] == session["source"],
            "original snapshot identity differs",
        )

    def _activation(self, import_id, operation_id):
        session = self._packet(import_id)
        packet = _contained(self.root, import_id)
        path = _contained(packet, "activation/" + _identifier(operation_id) + ".json")
        intent = self._document(path, _SCHEMA + "#/$defs/activation")
        derived = content_hash(
            {
                "importId": import_id,
                "validationHash": intent["validationHash"],
                "expectedHeadHash": intent["expectedHeadHash"],
            }
        )
        _require(
            intent["operationId"] == operation_id == derived
            and intent["importId"] == import_id
            and intent["phase"] == "prepared",
            "activation recovery identity differs",
        )
        receipt = self._document(
            _contained(packet, "validations/" + intent["validationHash"] + ".json"),
            _SCHEMA + "#/$defs/validation",
            intent["validationHash"],
        )
        _require(
            receipt["importId"] == import_id
            and receipt["ready"]
            and not receipt["findings"],
            "activation recovery lacks a ready receipt",
        )
        _require(
            receipt["locks"]["source"] == session["source"]
            and receipt["locks"]["expectedHeadHash"] == intent["expectedHeadHash"],
            "activation recovery source/target differs",
        )
        proposal_hash = receipt["locks"]["proposalHash"]
        proposal = self._document(
            _contained(packet, "proposals/" + proposal_hash + ".json"),
            _SCHEMA + "#/$defs/proposal",
            proposal_hash,
        )
        _require(
            proposal["importId"] == import_id
            and not proposal["findings"]
            and not proposal["provisionalFinishing"],
            "activation recovery proposal has unresolved content",
        )
        return intent

    def _canonical_index(self):
        if self.index is not None:
            return self.index
        store = self.workspace.store("cmap")
        if not store.path.is_file():
            return None
        index = self._document(store.path, keep=False)
        store._validate_index(index)
        _require(
            len(index["revisionRefs"]) <= MAX_REVISIONS,
            "canonical revision count exceeds retention limit",
        )
        self.index = index
        self.revision_refs = {
            reference["revisionId"]: reference for reference in index["revisionRefs"]
        }
        return index

    def _canonical_revision(self, revision_id):
        if revision_id in self.revisions:
            return self.revisions[revision_id]
        self._canonical_index()
        reference = self.revision_refs[revision_id]
        path = _contained(self.timeline, reference["path"])
        body = self._document(path, keep=False)
        store = self.workspace.store("cmap")
        store._validate_revision(body)
        _require(
            body["contentSha256"] == reference["contentSha256"],
            "canonical revision reference hash differs",
        )
        self.revisions[revision_id] = store._compat_revision(body)
        return self.revisions[revision_id]

    def _canonical_revisions(self):
        if self._canonical_index() is not None:
            for revision_id in self.revision_refs:
                self._canonical_revision(revision_id)

    def _history(self):
        self._canonical_revisions()
        for revision in self.revisions.values():
            for path in verify_import_origin(self.workspace, revision):
                self._keep(path)
            origin = revision["snapshot"].get("originRef")
            if origin is not None:
                self._packet(origin["importId"])
            for reference in revision["evidence"]:
                if reference.get("kind") == "timeline-import-return":
                    self._return_reference(revision, reference)

    def _return_reference(self, revision, reference):
        path = _contained(self.timeline, reference["path"])
        _require(path.is_relative_to(self.root), "return evidence escapes imports root")
        data = self._read(path)
        _require(
            hashlib.sha256(data).hexdigest() == reference["sha256"],
            "return intent file-byte fingerprint differs",
        )
        intent = self._return_intent(path)
        _require(
            reference["evidenceId"] == "return-" + intent["operationId"],
            "canonical return evidence identity differs",
        )
        self._return_revision(intent, revision)

    def _return_intent(self, path):
        path = Path(path).resolve()
        intent = self._document(path, _SCHEMA + "#/$defs/returnIntent")
        operation = content_hash(
            {
                "kind": "return",
                "activationId": intent["activationId"],
                "expectedHeadHash": intent["expectedHeadHash"],
            }
        )
        packet = _contained(self.root, _identifier(intent["importId"]))
        _require(
            path == _contained(packet, "returns/" + operation + ".json")
            and intent["operationId"] == operation
            and intent["phase"] == "prepared",
            "return intent identity/path differs",
        )
        activation = self._activation(intent["importId"], intent["activationId"])
        target = self._canonical_revision(intent["targetRevisionId"])
        _require(
            activation["previousRevisionId"] == target["revisionId"]
            and activation["previousSnapshot"] == target["snapshot"],
            "return target differs from recorded pre-activation content",
        )
        _require(
            target["contentHash"] == intent["targetRevisionHash"],
            "return target revision hash differs",
        )
        self._return_owner(intent, activation)
        return intent

    def _return_owner(self, intent, activation):
        owner = self._canonical_revision(activation["revisionId"])
        origin = owner["snapshot"]["originRef"]
        _require(
            (origin["importId"], origin["activationId"])
            == (intent["importId"], intent["activationId"]),
            "return owner activation differs",
        )
        for path in verify_import_origin(self.workspace, owner):
            self._keep(path)

    def _return_revision(self, intent, revision):
        _require(
            intent["revisionId"] == revision["revisionId"],
            "return canonical revision differs",
        )
        parent = self._canonical_revision(revision["parentRevisionId"])
        _require(
            parent["contentHash"] == intent["expectedHeadHash"],
            "return canonical parent differs",
        )
        _require(
            revision["createdAt"] == intent["createdAt"]
            and all(
                revision[key] == intent[key].strip() for key in ("actor", "reason")
            ),
            "return canonical metadata differs",
        )
        target = deepcopy(
            self._canonical_revision(intent["targetRevisionId"])["snapshot"]
        )
        actual = deepcopy(revision["snapshot"])
        sync = actual.pop("syncRef")
        target.pop("syncRef", None)
        _require(
            actual == target
            and sync["contentSha256"] == intent["sync"]["revisionHash"],
            "returned content/current Sync differs",
        )
        completed = {
            **intent,
            "phase": "reconciled",
            "revisionHash": revision["contentHash"],
        }
        packet = _contained(self.root, intent["importId"])
        path = _contained(packet, "return-results/" + content_hash(completed) + ".json")
        result = self._document(path, semantic=path.stem)
        _require(result == completed, "return reconciliation record differs")

    def _pending(self):
        path = self.timeline / "import-activation.pending.json"
        if not path.exists():
            return
        _require(path.stat().st_size <= 4096, "pending marker exceeds retention limit")
        marker = self._document(path)
        _require(
            set(marker) == {"importId", "operationId"},
            "pending marker has unknown fields",
        )
        import_id, operation_id = (
            _identifier(marker["importId"]),
            _identifier(marker["operationId"]),
        )
        self._packet(import_id)
        packet = _contained(self.root, import_id)
        candidates = [
            packet / kind / (operation_id + ".json")
            for kind in ("activation", "returns")
        ]
        candidates = [candidate for candidate in candidates if candidate.is_file()]
        _require(
            len(candidates) == 1, "pending marker does not identify one exact operation"
        )
        self._pending_operation(candidates[0], import_id, operation_id)

    def _pending_operation(self, path, import_id, operation_id):
        if path.parent.name == "activation":
            self._activation(import_id, operation_id)
            return
        intent = self._return_intent(path)
        revision = self.revisions.get(intent["revisionId"])
        if revision is not None:
            self._return_revision(intent, revision)

    def collect(self):
        self._history()
        self._pending()
        return sorted(self.paths, key=str)

    def return_paths(self, revision):
        actual = self._canonical_revision(revision["revisionId"])
        _require(
            all(
                actual[key] == revision[key]
                for key in (
                    "revisionId",
                    "parentRevisionId",
                    "contentHash",
                    "snapshot",
                    "evidence",
                )
            ),
            "supplied return revision differs from immutable canonical body",
        )
        for reference in actual["evidence"]:
            if reference.get("kind") == "timeline-import-return":
                self._return_reference(actual, reference)
        return sorted(self.paths, key=str)


def _checked_paths(workspace, revision=None):
    try:
        with fingerprint_stage(verify_on_exit=True):
            retention = _Retention(workspace)
            return (
                retention.collect()
                if revision is None
                else retention.return_paths(revision)
            )
    except LineageError:
        raise
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
        raise LineageError(f"Cannot retain timeline import evidence: {exc}") from exc


def retained_import_paths(workspace):
    """Retain referenced import/return history; never preserve all staged packets."""
    return _checked_paths(workspace)


def retained_return_paths(workspace, revision):
    """Verify one canonical return without selecting or traversing other origins."""
    return _checked_paths(workspace, revision)
