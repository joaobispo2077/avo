"""Records and coordination for optional ArtCraft authoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from avo.paths import repo_root
from avo.timeline.contracts import ContractError, content_hash, validate_document
from avo.timeline.store import (
    StoreError,
    atomic_write_json,
    timeline_writer,
    write_immutable_json,
)

__all__ = [
    "ArtCraftError",
    "ArtCraftIntent",
    "ArtCraftJobStore",
    "CurrentArtCraftRoutes",
    "PinnedArtCraftComponent",
    "assess_request",
    "catalog",
    "guard_legacy_component_request",
    "require_eligible",
    "seal_record",
    "validate_record",
]

_SEALED = frozenset({"decision", "job", "event", "package", "receipt"})
_OPERATIONAL_FAILURES = frozenset(
    {"not-installed", "invalid-input", "permission-denied", "transient-error", "defect"}
)


class ArtCraftError(ValueError):
    """A request cannot proceed within its confirmed scope and evidence."""

    def __init__(self, message, *, code="ARTCRAFT_INVALID_REQUEST"):
        super().__init__(message)
        self.code = code

    def to_dict(self):
        return {"code": self.code, "message": str(self), "blocking": True}


@dataclass(frozen=True)
class ArtCraftIntent:
    """A selection from the current invocation, outside source/request data."""

    kind: str = "ordinary"
    app: str | None = None
    operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class CurrentArtCraftRoutes:
    """Current native/reuse facts supplied by AVO's trusted capability resolver."""

    provider: str
    component_id: str
    requirement_hash: str
    candidates: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PinnedArtCraftComponent:
    """A selected version and current reuse result from component resolution."""

    provider: str
    component_id: str
    requirement_hash: str
    package_hash: str
    app: str
    operations: tuple[str, ...]
    reusable: bool


def _matches_requirement(request, resolved):
    return (
        resolved.provider == request["provider"]
        and resolved.component_id == request["componentId"]
        and resolved.requirement_hash == content_hash(request["required"])
    )


def _scope(app, operations):
    return validate_document(
        {"app": app, "operations": list(operations)}, _schema("scope")
    )


def _selection(request, intent, candidates, pinned):
    selected_app = intent.app or (pinned.app if pinned is not None else None)
    exclusions = set(request["exclusions"])
    motion = request["required"]["outputRole"] in {"overlay-video", "generated-clip"}
    if exclusions & {"artcraft", "other-authoring", selected_app} or (
        motion and "motion" in exclusions
    ):
        return "blocked", "excluded-or-conflicting", {}
    if intent.kind == "knowledge":
        return "existing", "knowledge-only", {}
    if intent.kind == "explicit":
        return (
            "eligible",
            "explicit-request",
            {"scope": _scope(intent.app, intent.operations)},
        )
    if pinned is not None:
        return _pinned_selection(request, intent, pinned)
    return _native_selection(request, intent, candidates)


def _pinned_selection(request, intent, pinned):
    if not _matches_requirement(request, pinned) or intent.app not in (
        None,
        pinned.app,
    ):
        return "blocked", "excluded-or-conflicting", {}
    evidence = {"packageHash": pinned.package_hash}
    if pinned.reusable:
        return "existing", "reuse-current", evidence
    return (
        "eligible",
        "recorded-component",
        {**evidence, "scope": _scope(pinned.app, pinned.operations)},
    )


def _native_selection(request, intent, candidates):
    statuses = {candidate["status"] for candidate in candidates}
    if "sufficient" in statuses:
        return "existing", "native-sufficient", {}
    if statuses & _OPERATIONAL_FAILURES:
        return "blocked", "native-operational-failure", {}
    if intent.kind == "gap":
        return _gap_selection(request, intent, candidates, statuses)
    if not statuses or "unknown" in statuses:
        return (
            "needs-input",
            "capability-undetermined",
            {
                "missingInputs": [
                    "Current capability and reuse contracts for this requirement"
                ]
            },
        )
    return (
        "needs-input",
        "gap-evidence-incomplete",
        {"missingInputs": ["Selected app and operations for the required gap"]},
    )


def _gap_selection(request, intent, candidates, statuses):
    if (
        statuses == {"unsupported"}
        and len({item["route"] for item in candidates}) == len(candidates)
        and all(item.get("reason", "").strip() for item in candidates)
        and sorted(map(content_hash, request["candidates"]))
        == sorted(map(content_hash, candidates))
    ):
        return (
            "eligible",
            "capability-gap",
            {"scope": _scope(intent.app, intent.operations)},
        )
    return (
        "needs-input",
        "gap-evidence-incomplete",
        {
            "missingInputs": [
                "Exact current unsupported contracts for every considered route"
            ]
        },
    )


def assess_request(request, *, intent=None, routes=None, pinned=None):
    """Select from validated current facts without probing or launching anything."""
    request = validate_record("request", request)
    intent = intent if intent is not None else ArtCraftIntent()
    if intent.kind not in {"ordinary", "knowledge", "explicit", "gap"}:
        raise ArtCraftError("Unknown ArtCraft invocation intent")
    candidates = (
        list(routes.candidates)
        if routes and _matches_requirement(request, routes)
        else []
    )
    for candidate in candidates:
        validate_document(candidate, _schema("candidate"))
    disposition, reason, detail = _selection(request, intent, candidates, pinned)
    return seal_record(
        "decision",
        {
            "version": 1,
            "requestHash": content_hash(request),
            "provider": request["provider"],
            "componentId": request["componentId"],
            "disposition": disposition,
            "reason": reason,
            "checkedCandidates": candidates,
            "missingInputs": [],
            **detail,
        },
    )


def require_eligible(
    request, recorded_decision, *, intent=None, routes=None, pinned=None
):
    """Recompute eligibility at the trusted boundary immediately before IO."""
    current = assess_request(request, intent=intent, routes=routes, pinned=pinned)
    if current["disposition"] != "eligible":
        raise ArtCraftError(
            f"ArtCraft scope is ineligible: {current['reason']}",
            code="ARTCRAFT_NOT_ELIGIBLE",
        )
    if current != validate_record("decision", recorded_decision):
        raise ArtCraftError(
            "ArtCraft scope or evidence changed", code="ARTCRAFT_SCOPE_CHANGED"
        )
    return current


def guard_legacy_component_request(payload):
    """Reserve ArtCraft declarations for the authoring and admission path."""
    records = (
        payload,
        payload.get("instance"),
        payload.get("record"),
        payload.get("capabilityGap"),
    )
    if any(
        _declares_artcraft(record) for record in records if isinstance(record, dict)
    ):
        raise ArtCraftError(
            "ArtCraft components require a scoped authoring job and qualified admission",
            code="ARTCRAFT_ADMISSION_REQUIRED",
        )


def _declares_artcraft(record):
    if record.get("backend") == "artcraft" or "artcraft" in record:
        return True
    parameters = record.get("parameters")
    if isinstance(parameters, dict) and "artcraft" in parameters:
        return True
    generator = record.get("generator")
    generated_by = generator.get("adapterId") if isinstance(generator, dict) else None
    return any(
        isinstance(name, str)
        and (name == "artcraft" or name.startswith(("artcraft.", "artcraft-")))
        for name in (record.get("adapterId"), generated_by)
    )


def catalog(*, app: str | None = None, behavior: str | None = None) -> dict:
    """Return bundled knowledge, without probing any application or connection."""
    resource = files("avo.resources.artcraft").joinpath("catalog.json")
    index = json.loads(resource.read_text(encoding="utf-8"))
    profiles = index["profiles"]
    if app is not None:
        validate_document(app, _schema("app"))
        profiles = [profile for profile in profiles if profile["app"] == app]
    if behavior is not None:
        validate_document(behavior, _schema("id"))
        profiles = [
            profile for profile in profiles if behavior in profile["operations"]
        ]
    return {**index, "profiles": profiles}


def _schema(kind: str) -> str:
    return f"avo.artcraft.schema.json#/$defs/{kind}"


def seal_record(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    """Seal a new record with the canonical hash of its complete body."""
    if kind not in _SEALED:
        raise ContractError(f"ArtCraft record does not have a hash field: {kind}")
    field = f"{kind}Hash"
    if field in body:
        raise ContractError(f"ArtCraft {field} must be computed from the record body")
    return validate_record(kind, {**body, field: content_hash(body)})


def validate_record(kind: str, record: dict[str, Any]) -> dict[str, Any]:
    """Check record shape and stable identity without consulting native apps."""
    if kind not in _SEALED | {"request"}:
        raise ContractError(f"unknown ArtCraft record type: {kind}")
    validate_document(record, _schema(kind))
    if kind in _SEALED:
        field = f"{kind}Hash"
        if (
            content_hash({key: value for key, value in record.items() if key != field})
            != record[field]
        ):
            raise ContractError(f"ArtCraft {field} does not match its contents")
    if kind == "job":
        validate_record("decision", record["decision"])
        _check_job_identity(record)
    return record


def _check_job_identity(job):
    request = job["request"]
    decision = job["decision"]
    if decision["disposition"] != "eligible":
        raise ContractError("ArtCraft job requires an eligible decision")
    if (
        decision["requestHash"] != content_hash(request)
        or decision["provider"] != request["provider"]
        or decision["componentId"] != request["componentId"]
    ):
        raise ContractError("ArtCraft decision does not match its request scope")
    scope = decision["scope"]
    observation = job["observation"]
    if scope["app"] != observation["app"] or not set(scope["operations"]).issubset(
        observation["operations"]
    ):
        raise ContractError(
            "ArtCraft observation does not cover the selected operations"
        )
    if job["output"]["role"] != request["required"]["outputRole"]:
        raise ContractError("ArtCraft output role does not match the request")


def _bounded_path(root: Path, path: Path, label: str) -> Path:
    if (
        not path.is_absolute()
        or not path.is_relative_to(root)
        or path.resolve() != path
    ):
        raise ArtCraftError(f"ArtCraft {label} must stay inside {root}")
    return path


def _read_record(path: Path) -> dict:
    if path.stat().st_nlink != 1:
        raise ArtCraftError(f"ArtCraft record has an external file alias: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


class ArtCraftJobStore:
    """Immutable job and event records with a compare-and-swap event pointer."""

    def __init__(self, workspace: Path, *, metadata_root: Path | None = None):
        workspace = Path(workspace)
        if not workspace.is_absolute() or workspace.resolve(strict=True) != workspace:
            raise ArtCraftError(
                "ArtCraft workspace must be an exact absolute directory"
            )
        repository = repo_root().resolve()
        if (
            not workspace.is_dir()
            or workspace.is_relative_to(repository)
            or repository.is_relative_to(workspace)
        ):
            raise ArtCraftError("ArtCraft workspace must be outside the AVO repository")
        self.workspace = workspace
        self.directory = _bounded_path(
            workspace,
            Path(metadata_root) if metadata_root else workspace / "artcraft-jobs",
            "metadata directory",
        )
        if self.directory == self.workspace:
            raise ArtCraftError(
                "ArtCraft metadata directory must be dedicated to job records"
            )

    def _job_dir(self, job_id: str) -> Path:
        validate_document(job_id, _schema("id"))
        return _bounded_path(
            self.directory, self.directory / f"job-{job_id}", "job directory"
        )

    def _job_path(self, job_id: str) -> Path:
        directory = self._job_dir(job_id)
        return _bounded_path(directory, directory / "job.json", "job record")

    def _writer(self):
        lock = _bounded_path(
            self.workspace, self.directory / ".mutation.lock", "job writer lock"
        )
        if lock.exists() and lock.stat().st_nlink != 1:
            raise ArtCraftError("ArtCraft job writer lock has an external file alias")
        return timeline_writer(self.directory)

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        job = seal_record("job", body)
        if Path(job["workspace"]) != self.workspace:
            raise ArtCraftError(
                "ArtCraft job workspace differs from the selected workspace"
            )
        for root in job["roots"]["write"]:
            _bounded_path(self.workspace, Path(root), "write root")
        with self._writer():
            path = self._job_path(job["jobId"])
            if path.exists():
                stored = self.load(job["jobId"])
                if stored != job:
                    raise ArtCraftError(
                        "ArtCraft job already exists with different content"
                    )
                return stored
            write_immutable_json(path, job)
        return job

    def load(self, job_id: str) -> dict[str, Any]:
        job = validate_record("job", _read_record(self._job_path(job_id)))
        if job["jobId"] != job_id or Path(job["workspace"]) != self.workspace:
            raise ArtCraftError(
                "ArtCraft stored job does not match its workspace and ID"
            )
        return job

    def _event(self, job_dir, operation_id, job_hash):
        validate_document(operation_id, _schema("id"))
        path = _bounded_path(
            job_dir, job_dir / f"event-{operation_id}.json", "event record"
        )
        event = validate_record("event", _read_record(path))
        if event["jobHash"] != job_hash or event["operationId"] != operation_id:
            raise ArtCraftError(
                "ArtCraft event belongs to a different job or operation"
            )
        return event

    @staticmethod
    def _index_path(job_dir):
        return _bounded_path(job_dir, job_dir / "events.json", "event index")

    def _index(self, job_dir):
        try:
            index = _read_record(self._index_path(job_dir))
        except FileNotFoundError:
            return {"head": None, "operations": {}}
        validate_document(index, _schema("eventIndex"))
        if index["head"] not in index["operations"]:
            raise ArtCraftError("ArtCraft event index has no matching head")
        return index

    def _indexed_event(self, directory, operation_id, digest, job_hash):
        event = self._event(directory, operation_id, job_hash)
        if event["eventHash"] != digest:
            raise ArtCraftError("ArtCraft event index and record do not match")
        return event

    def head(self, job_id: str) -> dict[str, Any] | None:
        job = self.load(job_id)
        directory = self._job_dir(job_id)
        return self._head_from_index(job, directory, self._index(directory))

    def _head_from_index(self, job, directory, index):
        operation_id = index["head"]
        if operation_id is None:
            return None
        return self._indexed_event(
            directory, operation_id, index["operations"][operation_id], job["jobHash"]
        )

    def append(
        self, job_id: str, *, expected_head: str, event: dict[str, Any]
    ) -> dict[str, Any]:
        operation_id = event.get("operationId")
        validate_document(operation_id, _schema("id"))
        with self._writer():
            job = self.load(job_id)
            directory = self._job_dir(job_id)
            index = self._index(directory)
            operations = index["operations"]
            if operation_id in operations:
                previous = self._indexed_event(
                    directory, operation_id, operations[operation_id], job["jobHash"]
                )
                if _event_record(job, event, previous["predecessorHash"]) != previous:
                    raise ArtCraftError(
                        "ArtCraft operationId already used for different content"
                    )
                if expected_head not in (
                    previous["predecessorHash"] or "empty",
                    previous["eventHash"],
                ):
                    raise ArtCraftError(
                        "ArtCraft operation replay has a different expected head"
                    )
                return previous
            current = self._head_from_index(job, directory, index)
            predecessor = current["eventHash"] if current else None
            if expected_head != (predecessor or "empty"):
                raise ArtCraftError(
                    f"ArtCraft expected head {expected_head} differs from {predecessor or 'empty'}"
                )
            record = _event_record(job, event, predecessor)
            next_index = {
                "head": operation_id,
                "operations": {**operations, operation_id: record["eventHash"]},
            }
            validate_document(next_index, _schema("eventIndex"))
            path = _bounded_path(
                directory, directory / f"event-{operation_id}.json", "event record"
            )
            try:
                write_immutable_json(path, record)
            except StoreError as exc:
                raise ArtCraftError(
                    f"ArtCraft operationId conflicts with retained evidence: {operation_id}"
                ) from exc
            atomic_write_json(self._index_path(directory), next_index)
            return record


def _event_record(job, event, predecessor):
    if {"version", "jobHash", "predecessorHash", "eventHash"} & event.keys():
        raise ArtCraftError("ArtCraft event identity is assigned by the job store")
    return seal_record(
        "event",
        {
            **event,
            "version": 1,
            "jobHash": job["jobHash"],
            "predecessorHash": predecessor,
        },
    )
