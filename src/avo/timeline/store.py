"""Validated index + immutable revision/event storage for external projects.

The JSON file at ``edit/timeline/<artifact>.json`` is a small mutable index.
Revision and event bodies are immutable sidecars. ``load()`` hydrates a legacy
view for the existing renderer-policy adapters; ``load_index()`` is canonical.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from .contracts import ContractError, content_hash, validate_document

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class StoreError(RuntimeError):
    """Raised when a canonical write would violate immutable history."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _actor(value: str | dict[str, Any], *, default_type: str = "agent", tool_version: str = "avo") -> dict[str, str]:
    if isinstance(value, dict):
        actor = {key: str(item).strip() for key, item in value.items() if str(item).strip()}
    else:
        actor = {"type": default_type, "id": str(value).strip(), "toolVersion": tool_version}
    if not actor.get("id"):
        raise StoreError("actor identity is required")
    actor.setdefault("type", default_type)
    return actor


def _require_sha256(value: str, label: str) -> str:
    value = str(value)
    if not _SHA256.fullmatch(value):
        raise StoreError(f"{label} must be an exact lowercase sha256")
    return value


def _slug(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9-]+", "-", value).strip("-").lower()
    return result or "artifact"


def atomic_write_json(path: Path, value: Any) -> Path:
    """Write JSON through a sibling temp file and atomic replace.

    File fsync happens before replacement. Parent fsync is best-effort because it
    is unavailable on some Windows/file-share combinations.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
        try:
            descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            descriptor = None
        if descriptor is not None:
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return path


class ArtifactStore:
    """Canonical artifact index backed by immutable sidecar bodies."""

    def __init__(self, path: Path, *, clock: Callable[[], str] = now_iso):
        self.path = Path(path)
        self.clock = clock

    @property
    def timeline_dir(self) -> Path:
        return self.path.parent

    def _revision_dir(self, index: dict[str, Any]) -> Path:
        return self.timeline_dir / "revisions" / str(index["artifactType"]) / _slug(str(index["artifactId"]))

    def _event_dir(self, index: dict[str, Any]) -> Path:
        return self.timeline_dir / "events" / _slug(str(index["artifactId"]))

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.timeline_dir).as_posix()

    def initialize(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        video_id: str,
        provider: str,
        timeline_domain: str,
        schema_version: str = "1.0.0",
    ) -> dict[str, Any]:
        if self.path.exists():
            return self.load()
        timestamp = self.clock()
        index = {
            "schemaVersion": schema_version,
            "artifactType": artifact_type,
            "artifactId": artifact_id,
            "videoId": video_id,
            "provider": provider,
            "timelineDomain": timeline_domain,
            "headRevisionId": None,
            "approvedRevisionId": None,
            "revisionRefs": [],
            "eventRefs": [],
            "activeState": "valid",
            "updatedAt": timestamp,
        }
        self._validate_index(index)
        self._revision_dir(index).mkdir(parents=True, exist_ok=True)
        self._event_dir(index).mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, index)
        return self.load()

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StoreError(f"cannot load canonical document {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise StoreError(f"canonical document must be an object: {path}")
        return value

    def _validate_index(self, index: dict[str, Any]) -> None:
        try:
            validate_document(index, "avo.timeline-index.schema.json")
        except ContractError as exc:
            raise StoreError(f"invalid artifact index {self.path}: {exc}") from exc
        ids = [str(item["revisionId"]) for item in index["revisionRefs"]]
        if len(ids) != len(set(ids)):
            raise StoreError("artifact index contains duplicate revision IDs")
        if index["headRevisionId"] is not None and index["headRevisionId"] not in ids:
            raise StoreError("head revision is not present in revisionRefs")
        if index["approvedRevisionId"] is not None and index["approvedRevisionId"] not in ids:
            raise StoreError("approved revision is not present in revisionRefs")

    def load_index(self) -> dict[str, Any]:
        index = self._read_json(self.path)
        if "revisionRefs" not in index:
            raise StoreError(
                f"legacy embedded artifact requires migration before canonical writes: {self.path}"
            )
        self._validate_index(index)
        for ref in index["revisionRefs"]:
            revision = self._read_json(self.timeline_dir / ref["path"])
            self._validate_revision(revision)
            if revision["contentSha256"] != ref["contentSha256"]:
                raise StoreError(f"revision ref hash mismatch: {ref['revisionId']}")
        for ref in index["eventRefs"]:
            event = self._read_json(self.timeline_dir / ref["path"])
            self._validate_event(event)
            if content_hash(event) != ref["sha256"]:
                raise StoreError(f"event ref hash mismatch: {ref['eventId']}")
        return deepcopy(index)

    def _validate_revision(self, revision: dict[str, Any]) -> None:
        try:
            validate_document(revision, "avo.timeline-revision.schema.json")
        except ContractError as exc:
            raise StoreError(f"invalid immutable revision: {exc}") from exc
        body = {key: value for key, value in revision.items() if key != "contentSha256"}
        if content_hash(body) != revision["contentSha256"]:
            raise StoreError(f"immutable revision hash mismatch: {revision.get('revisionId')}")

    def _validate_event(self, event: dict[str, Any]) -> None:
        try:
            validate_document(event, "avo.timeline-event.schema.json")
        except ContractError as exc:
            raise StoreError(f"invalid immutable event: {exc}") from exc

    def _revision_body(self, index: dict[str, Any], revision_id: str) -> dict[str, Any]:
        ref = next((item for item in index["revisionRefs"] if item["revisionId"] == revision_id), None)
        if ref is None:
            raise StoreError(f"revision does not exist: {revision_id}")
        revision = self._read_json(self.timeline_dir / ref["path"])
        self._validate_revision(revision)
        return revision

    @staticmethod
    def _compat_revision(revision: dict[str, Any]) -> dict[str, Any]:
        return {
            "revisionId": revision["revisionId"],
            "parentRevisionId": revision["parentRevisionId"],
            "createdAt": revision["createdAt"],
            "actor": revision["actor"]["id"],
            "reason": revision["reason"],
            "snapshot": deepcopy(revision["snapshot"]),
            "diff": deepcopy(revision["diff"]),
            "dependencies": deepcopy(revision["basis"]),
            "evidence": deepcopy(revision["inputEvidenceRefs"]),
            "state": "draft",
            "contentHash": revision["contentSha256"],
        }

    @staticmethod
    def _compat_event(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "decisionId": event["eventId"],
            "decision": event["type"],
            "revisionId": event["subject"]["revisionId"],
            "revisionHash": event["subject"]["contentSha256"],
            "candidateHash": event.get("candidateSha256"),
            "dependencyHashes": deepcopy(event.get("dependencyHashes") or {}),
            "actor": event["actor"]["id"],
            "decidedAt": event["occurredAt"],
            "reason": event["reason"],
            "scope": event.get("scope"),
        }

    def load(self) -> dict[str, Any]:
        """Return a hydrated compatibility view; never write this representation."""
        index = self.load_index()
        revisions = [self._compat_revision(self._revision_body(index, ref["revisionId"])) for ref in index["revisionRefs"]]
        decisions = []
        for ref in index["eventRefs"]:
            event = self._read_json(self.timeline_dir / ref["path"])
            if event["type"] in {"approved", "rejected", "changes-requested", "promotion-approved"}:
                decisions.append(self._compat_event(event))
        return {
            "schemaVersion": index["schemaVersion"],
            "artifactType": index["artifactType"],
            "artifactId": index["artifactId"],
            "videoId": index["videoId"],
            "provider": index["provider"],
            "timelineDomain": index["timelineDomain"],
            "currentRevisionId": index["headRevisionId"],
            "approvedRevisionId": index["approvedRevisionId"],
            "revisions": revisions,
            "decisions": decisions,
            "activeState": index["activeState"],
        }

    def _head_hash(self, index: dict[str, Any]) -> str | None:
        head = index["headRevisionId"]
        if head is None:
            return None
        return next(item["contentSha256"] for item in index["revisionRefs"] if item["revisionId"] == head)

    def append_revision(
        self,
        *,
        snapshot: dict[str, Any],
        actor: str | dict[str, Any],
        reason: str,
        parent_revision_id: str | None = None,
        diff: list[dict[str, Any]] | None = None,
        dependencies: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        state: str = "draft",
        revision_id: str | None = None,
        created_at: str | None = None,
        expected_head_hash: str | None = None,
    ) -> dict[str, Any]:
        del state  # effective state is derived; retained in API for legacy callers.
        if not str(reason).strip():
            raise StoreError("revision reason is required")
        index = self.load_index()
        actual_head_hash = self._head_hash(index)
        if expected_head_hash is not None and actual_head_hash != expected_head_hash:
            raise StoreError(f"compare-and-swap failed: expected head {expected_head_hash}, actual {actual_head_hash}")
        existing = {item["revisionId"] for item in index["revisionRefs"]}
        revision_id = revision_id or f"{index['artifactType']}-r{len(existing) + 1:04d}"
        if revision_id in existing:
            raise StoreError(f"revision id already exists: {revision_id}")
        current = index["headRevisionId"]
        if parent_revision_id is None and current is not None:
            parent_revision_id = current
        if parent_revision_id is not None and parent_revision_id not in existing:
            raise StoreError(f"parent revision does not exist: {parent_revision_id}")
        if parent_revision_id == revision_id:
            raise StoreError("revision cannot parent itself")
        timestamp = created_at or self.clock()
        body: dict[str, Any] = {
            "schemaVersion": "1.0.0",
            "artifactType": index["artifactType"],
            "artifactId": index["artifactId"],
            "revisionId": revision_id,
            "parentRevisionId": parent_revision_id,
            "createdAt": timestamp,
            "actor": _actor(actor),
            "reason": str(reason).strip(),
            "timelineDomain": index["timelineDomain"],
            "basis": deepcopy(dependencies or []),
            "snapshot": deepcopy(snapshot),
            "diff": deepcopy(diff or []),
            "inputEvidenceRefs": deepcopy(evidence or []),
        }
        body["contentSha256"] = content_hash(body)
        self._validate_revision(body)
        revision_path = self._revision_dir(index) / f"{revision_id}.json"
        if revision_path.exists():
            raise StoreError(f"immutable revision already exists: {revision_path}")
        atomic_write_json(revision_path, body)
        ref = {
            "revisionId": revision_id,
            "path": self._relative(revision_path),
            "contentSha256": body["contentSha256"],
            "createdAt": timestamp,
            "parentRevisionId": parent_revision_id,
        }
        updated = deepcopy(index)
        updated["revisionRefs"].append(ref)
        updated["headRevisionId"] = revision_id
        updated["activeState"] = "valid"
        updated.pop("stateReason", None)
        updated["updatedAt"] = timestamp
        self._validate_index(updated)
        atomic_write_json(self.path, updated)
        return self._compat_revision(body)

    def revision(self, revision_id: str) -> dict[str, Any]:
        return self._compat_revision(self._revision_body(self.load_index(), revision_id))

    def _append_event(self, index: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        self._validate_event(event)
        event_path = self._event_dir(index) / f"{event['eventId']}.json"
        if event_path.exists():
            raise StoreError(f"immutable event already exists: {event['eventId']}")
        atomic_write_json(event_path, event)
        updated = deepcopy(index)
        updated["eventRefs"].append({
            "eventId": event["eventId"], "path": self._relative(event_path),
            "sha256": content_hash(event), "type": event["type"], "occurredAt": event["occurredAt"],
        })
        updated["updatedAt"] = event["occurredAt"]
        return updated

    def record_decision(
        self, *, decision: str, revision_id: str, revision_hash: str,
        candidate_hash: str, dependency_hashes: dict[str, str], actor: str | dict[str, Any],
        checkpoint: str, scope: str, reason: str, evidence_bundle_hash: str,
        decided_at: str | None = None,
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected", "changes-requested", "promotion-approved"}:
            raise StoreError(f"unsupported decision: {decision}")
        if not dependency_hashes:
            raise StoreError("decision requires exact dependency hashes")
        dependency_hashes = {str(k): _require_sha256(v, f"dependency {k}") for k, v in sorted(dependency_hashes.items())}
        revision_hash = _require_sha256(revision_hash, "revision hash")
        candidate_hash = _require_sha256(candidate_hash, "candidate hash")
        evidence_bundle_hash = _require_sha256(evidence_bundle_hash, "evidence bundle hash")
        if not str(scope).strip() or not str(checkpoint).strip() or not str(reason).strip():
            raise StoreError("decision checkpoint, scope, and reason are required")
        index = self.load_index()
        revision = self._revision_body(index, revision_id)
        if revision["contentSha256"] != revision_hash:
            raise StoreError("decision revision hash does not match immutable body")
        timestamp = decided_at or self.clock()
        event_id = f"event-{decision}-{len(index['eventRefs']) + 1:04d}"
        event = {
            "schemaVersion": "1.0.0", "eventId": event_id, "type": decision,
            "occurredAt": timestamp, "actor": _actor(actor, default_type="user"),
            "subject": {"artifactId": index["artifactId"], "revisionId": revision_id, "contentSha256": revision_hash},
            "checkpoint": str(checkpoint), "candidateSha256": candidate_hash,
            "dependencyHashes": dependency_hashes,
            "dependencyLockSha256": content_hash(dependency_hashes),
            "scope": str(scope), "reason": str(reason), "evidenceBundleSha256": evidence_bundle_hash,
        }
        updated = self._append_event(index, event)
        if decision in {"approved", "promotion-approved"}:
            updated["approvedRevisionId"] = revision_id
        self._validate_index(updated)
        atomic_write_json(self.path, updated)
        return deepcopy(event)

    def approve(self, revision_id: str, *, revision_hash: str, candidate_hash: str) -> dict[str, Any]:
        self.record_decision(
            decision="approved", revision_id=revision_id, revision_hash=revision_hash,
            candidate_hash=candidate_hash, dependency_hashes={"revision": revision_hash},
            actor="human", checkpoint="legacy-compatibility", scope="exact-candidate",
            reason="Explicit exact-revision approval", evidence_bundle_hash=revision_hash,
        )
        return self.revision(revision_id)

    def effective_approval(self) -> dict[str, Any] | None:
        index = self.load_index()
        if index["approvedRevisionId"] is None or index["approvedRevisionId"] != index["headRevisionId"]:
            return None
        for ref in reversed(index["eventRefs"]):
            if ref["type"] not in {"approved", "promotion-approved"}:
                continue
            event = self._read_json(self.timeline_dir / ref["path"])
            if event["subject"]["revisionId"] == index["headRevisionId"]:
                return event
        return None

    def set_active_state(self, state: str, *, reason: str, actor: str = "avo-lineage") -> dict[str, Any]:
        if state not in {"valid", "stale", "blocked", "superseded"}:
            raise StoreError(f"invalid active state: {state}")
        index = self.load_index()
        if index["headRevisionId"] is None:
            return index
        revision = self._revision_body(index, index["headRevisionId"])
        timestamp = self.clock()
        event = {
            "schemaVersion": "1.0.0", "eventId": f"event-invalidated-{len(index['eventRefs']) + 1:04d}",
            "type": "invalidated", "occurredAt": timestamp, "actor": _actor(actor),
            "subject": {"artifactId": index["artifactId"], "revisionId": revision["revisionId"], "contentSha256": revision["contentSha256"]},
            "reason": reason, "details": {"state": state},
        }
        updated = self._append_event(index, event)
        updated["activeState"] = state
        updated["stateReason"] = reason
        self._validate_index(updated)
        atomic_write_json(self.path, updated)
        return deepcopy(updated)
