"""Records and coordination for optional ArtCraft authoring."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from avo.paths import repo_root
from avo.telemetry import disk_free
from avo.timeline.contracts import (
    ContractError,
    content_hash,
    file_fingerprint,
    validate_document,
)
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
    "inspect_authoring",
    "prepare_authoring",
    "require_eligible",
    "run_authoring",
    "seal_record",
    "validate_record",
]

_SEALED = frozenset({"decision", "job", "event", "package", "receipt"})
_NATIVE_SUFFIXES = {"anicraft": ".anicraft"}
_OPERATIONAL_FAILURES = frozenset(
    {"not-installed", "invalid-input", "permission-denied", "transient-error", "defect"}
)


class ArtCraftError(ValueError):
    """A request cannot proceed within its confirmed scope and evidence."""

    def __init__(self, message, *, code="ARTCRAFT_INVALID_REQUEST", remediation=None):
        super().__init__(message)
        self.code = code
        self.remediation = remediation

    def to_dict(self):
        result = {"code": self.code, "message": str(self), "blocking": True}
        if self.remediation:
            result["remediation"] = self.remediation
        return result


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
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
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

    def reference(self, job_id: str) -> Path:
        directory = self._job_dir(job_id)
        return _bounded_path(directory, directory / "job.json", "job record")

    def writer(self):
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
        with self.writer():
            path = self.reference(job["jobId"])
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
        job = validate_record("job", _read_record(self.reference(job_id)))
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
        with self.writer():
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


def prepare_authoring(
    request, spec, *, decision, intent, adapter, routes=None, pinned=None
):
    """Observe one eligible environment and prepare a source-preserving job."""
    selected = require_eligible(
        request, decision, intent=intent, routes=routes, pinned=pinned
    )
    validate_document(spec, _schema("jobSpec"))
    store, base, project_facts = _preparation_workspace(request, spec)
    scope = selected["scope"]
    document = _owned_document(store, base, spec["jobId"], scope["app"])
    roots = _preparation_roots(spec, document.parent)
    source = _preparation_source(spec, roots, document)
    _require_preparation_capacity(store.workspace, spec["budget"], source)
    observation = adapter.observe(
        scope=scope,
        mode=spec["mode"],
        roots=roots,
        cli_path=spec.get("cliPath"),
        app_path=spec.get("appPath"),
    )
    _require_preparation_observation(observation, spec, roots)
    recipe = [scope, spec["document"]["state"], spec["output"]]
    authoring = spec.get("authoringParameters")
    if authoring is not None:
        recipe.append(authoring)
    job = {
        "version": 1,
        "jobId": spec["jobId"],
        "request": request,
        "decision": selected,
        "workspace": str(store.workspace),
        "roots": roots,
        "observation": observation,
        "document": document.relative_to(store.workspace).as_posix(),
        "documentState": spec["document"]["state"],
        "inputs": [source] if source else [],
        "recipeHash": content_hash(recipe),
        "output": spec["output"],
        "budget": spec["budget"],
        **project_facts,
    }
    if authoring is not None:
        job["authoringParameters"] = authoring
    return _publish_preparation(store, job, document, source)


def _preparation_workspace(request, spec):
    from avo.init_project import load_provider

    provider = request["provider"]
    if spec["provider"] != provider:
        raise ArtCraftError("ArtCraft provider differs from the current request")
    try:
        load_provider(provider)
    except (OSError, ValueError) as exc:
        raise ArtCraftError(
            f"ArtCraft provider could not be resolved: {provider}"
        ) from exc
    selected = Path(spec["workspace"])
    if request["context"]["kind"] == "provider-only":
        store = ArtCraftJobStore(selected)
        return store, store.workspace / "artcraft-media", {}
    return _video_preparation_workspace(selected, request)


def _video_preparation_workspace(selected, request):
    from avo.timeline.workspace import TimelineWorkspace

    context = request["context"]
    path = Path(context["project"])
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ArtCraftError("ArtCraft requires the exact absolute project path")
    project = TimelineWorkspace.from_project(path)
    if (
        project.raw_dir.resolve() != selected
        or project.project.get("provider") != request["provider"]
        or project.video_id != context["videoId"]
    ):
        raise ArtCraftError(
            "ArtCraft project, provider or raw workspace differs from the current request"
        )
    edit = selected / "edit"
    metadata = _bounded_path(
        edit, project.timeline_dir / "artcraft-jobs", "video job metadata"
    )
    store = ArtCraftJobStore(selected, metadata_root=metadata)
    return (
        store,
        edit / "artcraft-media",
        {
            "projectFingerprint": file_fingerprint(path),
            "canonicalHeads": project.active_dependency_snapshot(),
        },
    )


def _owned_document(store, base, job_id, app):
    suffix = _NATIVE_SUFFIXES.get(app)
    if suffix is None:
        raise ArtCraftError(
            f"No checked authoring profile for {app}", code="ARTCRAFT_NOT_READY"
        )
    return _bounded_path(
        store.workspace,
        base / f"job-{job_id}" / f"component{suffix}",
        "native document",
    )


def _preparation_roots(spec, owned):
    supplied = [Path(path) for path in spec["readRoots"]]
    for root in supplied:
        if (
            not root.is_absolute()
            or not root.is_dir()
            or root.resolve(strict=True) != root
        ):
            raise ArtCraftError(
                "ArtCraft read root must be an exact absolute directory"
            )
    return {"read": sorted({str(owned), *map(str, supplied)}), "write": [str(owned)]}


def _preparation_source(spec, roots, document):
    selected = spec["document"].get("source")
    if selected is None:
        return None
    source = Path(selected)
    if not any(source.is_relative_to(Path(root)) for root in roots["read"]):
        raise ArtCraftError("ArtCraft source falls outside the selected read roots")
    if (
        source.resolve(strict=True) != source
        or source.suffix != document.suffix
        or source.is_relative_to(document.parent)
    ):
        raise ArtCraftError(
            "ArtCraft source must be the exact selected native original"
        )
    metadata = source.stat()
    if (
        not source.is_file()
        or metadata.st_nlink != 1
        or metadata.st_size > spec["budget"]["bytes"]
    ):
        raise ArtCraftError(
            "ArtCraft native source exceeds the byte limit or has a file alias"
        )
    return file_fingerprint(source)


def _require_preparation_capacity(workspace, budget, source):
    if budget["bytes"] > disk_free(workspace):
        raise ArtCraftError(
            "ArtCraft workspace has insufficient verified free disk",
            code="ARTCRAFT_NOT_READY",
        )
    if source is not None and source["sizeBytes"] >= budget["bytes"]:
        raise ArtCraftError(
            "ArtCraft budget leaves no space for the selected output",
            code="ARTCRAFT_NOT_READY",
        )


def _require_preparation_observation(observation, spec, roots):
    validate_document(observation, _schema("observation"))
    authority = (
        observation.get("authority") == "operator"
        if spec["mode"] == "guided"
        else observation.get("effectiveRoots") == roots
    )
    if not authority or observation["mode"] != spec["mode"]:
        raise ArtCraftError(
            "ArtCraft effective roots or working mode were not independently established",
            code="ARTCRAFT_NOT_READY",
        )


def _publish_preparation(store, job, document, source):
    with store.writer():
        job = store.create(job)
        prior = store.head(job["jobId"])
        if prior is not None and prior["state"] != "prepared":
            raise ArtCraftError(
                "ArtCraft job already advanced beyond preparation",
                code="ARTCRAFT_SCOPE_CHANGED",
            )
        if source is not None:
            document = _bounded_path(store.workspace, document, "native document")
            _copy_native_source(document, source)
        elif document.exists():
            raise ArtCraftError(
                "ArtCraft empty job already contains a native document",
                code="ARTCRAFT_SCOPE_CHANGED",
            )
        event = store.append(
            job["jobId"],
            expected_head="empty",
            event={"operationId": "prepare", "state": "prepared"},
        )
    return {
        "status": "prepared",
        "job": job,
        "jobRef": str(store.reference(job["jobId"])),
        "head": event["eventHash"],
    }


def _copy_native_source(document, source):
    document.parent.mkdir(parents=True, exist_ok=True)
    if document.exists():
        _require_exact_copy(document, source)
        return
    with NamedTemporaryFile(
        "wb", dir=document.parent, prefix=".source-", delete=False
    ) as scratch:
        temporary = Path(scratch.name)
        try:
            with Path(source["locator"]).open("rb") as origin:
                _copy_bounded_bytes(origin, scratch, source["sizeBytes"])
            scratch.close()
            _require_exact_copy(temporary, source)
            os.link(temporary, document)
        finally:
            scratch.close()
            temporary.unlink(missing_ok=True)


def _copy_bounded_bytes(origin, scratch, size):
    remaining = size
    while chunk := origin.read(min(remaining + 1, 1024 * 1024)):
        remaining -= len(chunk)
        if remaining < 0:
            raise ArtCraftError("ArtCraft source changed during the job copy")
        scratch.write(chunk)
    scratch.flush()
    os.fsync(scratch.fileno())


def _require_exact_copy(path, original):
    current = file_fingerprint(path)
    if path.stat().st_nlink != 1 or current != {**original, "locator": str(path)}:
        raise ArtCraftError(
            "ArtCraft retained job copy differs from the source fingerprint",
            code="ARTCRAFT_SCOPE_CHANGED",
        )


def inspect_authoring(job_ref, *, expected_head):
    """Reconcile retained job evidence without changing files or starting an app."""
    store, job, head = _open_selected_job(job_ref, expected_head)
    return _inspection_result(store, job, head)


def _inspection_result(store, job, head):
    checks = {
        "project": _inspect_job_project(store, job),
        "inputs": _inspect_job_inputs(job),
        "nativeDocument": _inspect_job_document(store, job, head),
        "outputs": _inspect_job_outputs(job, head),
    }
    handoff = head.get("handoff")
    if handoff is not None:
        checks["handoff"] = _inspect_handoff(store, job, handoff)
    return {
        "status": "stale" if "changed" in checks.values() else "current",
        "state": head["state"],
        "jobRef": str(store.reference(job["jobId"])),
        "jobHash": job["jobHash"],
        "head": head["eventHash"],
        "checks": checks,
        **({"handoff": handoff} if handoff is not None else {}),
    }


def _inspect_handoff(store, job, handoff):
    directory = (store.workspace / job["document"]).parent
    roots = job["roots"]["write"]
    if handoff["locator"] == str(directory / "handoff.json") and _retained_job_file(
        handoff, roots
    ):
        recipe = _read_record(Path(handoff["locator"]))["recipe"]
        if recipe["locator"] == str(directory / "recipe.json") and _retained_job_file(
            recipe, roots
        ):
            return "current"
    return "changed"


def _open_selected_job(job_ref, expected_head):
    path = Path(job_ref)
    if (
        not path.is_absolute()
        or path.name != "job.json"
        or path.resolve(strict=True) != path
    ):
        raise ArtCraftError("Choose the exact absolute ArtCraft job record")
    record = validate_record("job", _read_record(path))
    workspace = Path(record["workspace"])
    metadata = _selected_job_metadata(path, workspace, record["request"]["context"])
    store = ArtCraftJobStore(workspace, metadata_root=metadata)
    if store.reference(record["jobId"]) != path:
        raise ArtCraftError(
            "ArtCraft job reference differs from its recorded workspace"
        )
    stored = store.load(record["jobId"])
    head = store.head(record["jobId"])
    if stored != record or head is None or head["eventHash"] != expected_head:
        raise ArtCraftError(
            "ArtCraft expected job event head changed or is missing",
            code="ARTCRAFT_SCOPE_CHANGED",
        )
    return store, stored, head


def _selected_job_metadata(path, workspace, context):
    if context["kind"] == "provider-only":
        return workspace / "artcraft-jobs"
    metadata = path.parent.parent
    if metadata.name != "artcraft-jobs":
        raise ArtCraftError(
            "Video ArtCraft jobs require a dedicated metadata directory"
        )
    return _bounded_path(workspace / "edit", metadata, "video job metadata")


def _inspect_job_project(store, job):
    request = job["request"]
    if request["context"]["kind"] == "provider-only":
        return "not-applicable"
    try:
        current_store, _, current = _video_preparation_workspace(
            store.workspace, request
        )
    except (OSError, ValueError, RuntimeError):
        return "changed"
    if current_store.directory != store.directory or any(
        job.get(key) != value for key, value in current.items()
    ):
        return "changed"
    return "current"


def _retained_job_file(expected, roots):
    path = Path(expected["locator"])
    try:
        path = _bounded_path(_owning_root(path, roots), path, "retained file")
        return (
            path.is_file()
            and path.stat().st_nlink == 1
            and file_fingerprint(path) == expected
        )
    except (OSError, ValueError, RuntimeError):
        return False


def _owning_root(path, roots):
    for root in map(Path, roots):
        if root.is_absolute() and path.is_relative_to(root):
            return root
    raise ArtCraftError("ArtCraft evidence falls outside the approved roots")


def _inspect_job_inputs(job):
    return (
        "current"
        if all(_retained_job_file(item, job["roots"]["read"]) for item in job["inputs"])
        else "changed"
    )


def _inspect_job_outputs(job, head):
    expected = head.get("outputs") or []
    if not expected:
        return "awaiting-output"
    recipe = head.get("recipe")
    if recipe is not None:
        expected = [recipe, *expected]
    return (
        "current"
        if all(_retained_job_file(item, job["roots"]["write"]) for item in expected)
        else "changed"
    )


def _inspect_job_document(store, job, head):
    path = store.workspace / job["document"]
    roots = job["roots"]["write"]
    saved = head.get("saved")
    if saved is None and job.get("documentState") == "saved" and job["inputs"]:
        saved = {**job["inputs"][0], "locator": str(path)}
    if saved is None:
        return _inspect_unrecorded_document(path, head.get("handoff"))
    return (
        "current"
        if saved["locator"] == str(path) and _retained_job_file(saved, roots)
        else "changed"
    )


def _inspect_unrecorded_document(path, handoff):
    if handoff is not None and path.is_file() and path.resolve() == path:
        return "returned-unverified"
    return "changed" if path.exists() else "awaiting-document"


def run_authoring(job_ref, *, expected_head, adapter):
    """Reserve the exact job once, then record inspected output or an unknown outcome."""
    store, _, _ = _open_selected_job(job_ref, expected_head)
    with store.writer():
        _, job, head = _open_selected_job(job_ref, expected_head)
        inspection = _inspection_result(store, job, head)
        if inspection["status"] != "current":
            raise ArtCraftError(
                "ArtCraft prepared job is stale", code="ARTCRAFT_SCOPE_CHANGED"
            )
        if head["state"] == "exported":
            _verify_retained_export(store, job, head)
            return inspection
        if job["observation"]["mode"] == "guided":
            return _run_guided(store, job, head, inspection, adapter)
        directory = _require_prepared_lower_third(store, job, head)
        adapter.validate_run(job)
        running = store.append(
            job["jobId"],
            expected_head=expected_head,
            event={"operationId": "run", "state": "running"},
        )
    return _execute_prepared_job(store, job, running, directory, adapter)


def _run_guided(store, job, head, inspection, adapter):
    if head["state"] == "ready" and inspection["checks"].get("handoff") == "current":
        return inspection
    directory = _require_prepared_lower_third(store, job, head)
    plan = adapter.plan_lower_third(job, directory)
    directory.mkdir(parents=True, exist_ok=True)
    recipe = _bounded_path(directory, directory / "recipe.json", "guided recipe")
    write_immutable_json(recipe, plan["steps"])
    handoff = _bounded_path(directory, directory / "handoff.json", "guided handoff")
    write_immutable_json(
        handoff,
        {
            "version": 1,
            "jobHash": job["jobHash"],
            "mode": "guided",
            "artifactState": "reference-only",
            "operatorRoots": job["roots"],
            "nativeDocument": str(directory / "component.anicraft"),
            "recipe": file_fingerprint(recipe),
            "commands": plan["commands"],
        },
    )
    event = store.append(
        job["jobId"],
        expected_head=head["eventHash"],
        event={
            "operationId": "guide",
            "state": "ready",
            "handoff": file_fingerprint(handoff),
        },
    )
    return _inspection_result(store, job, event)


def _require_prepared_lower_third(store, job, head):
    if head["state"] != "prepared":
        raise ArtCraftError(
            "ArtCraft job requires reconciliation before another operation",
            code="ARTCRAFT_OUTCOME_UNKNOWN",
        )
    scope = job["decision"]["scope"]
    if (
        scope != {"app": "anicraft", "operations": ["lower-third"]}
        or job.get("documentState") != "empty"
        or not job.get("authoringParameters")
    ):
        raise ArtCraftError(
            "ArtCraft runner needs an empty AniCraft document and the selected lower-third parameters",
            code="ARTCRAFT_NOT_ELIGIBLE",
        )
    directory = store.workspace / job["document"]
    if job["roots"]["write"] != [str(directory.parent)]:
        raise ArtCraftError(
            "ArtCraft job output does not match the verified write root",
            code="ARTCRAFT_SCOPE_CHANGED",
        )
    return _bounded_path(store.workspace, directory.parent, "job output")


def _execute_prepared_job(store, job, running, directory, adapter):
    try:
        result = adapter.author_lower_third(job, directory)
        evidence = _verify_authoring_result(job, directory, result)
        if (
            _inspect_job_project(store, job) == "changed"
            or _inspect_job_inputs(job) != "current"
        ):
            raise ArtCraftError(
                "ArtCraft input or project evidence changed while it was running"
            )
    except Exception as exc:
        pending = store.append(
            job["jobId"],
            expected_head=running["eventHash"],
            event={"operationId": "reconcile-run", "state": "outcome-unknown"},
        )
        raise ArtCraftError(
            "ArtCraft authoring did not produce independently verified job outputs",
            code="ARTCRAFT_OUTCOME_UNKNOWN",
            remediation=f"Inspect the retained job at head {pending['eventHash']} before attempting recovery.",
        ) from exc
    completed = store.append(
        job["jobId"],
        expected_head=running["eventHash"],
        event={"operationId": "verify-run", "state": "exported", **evidence},
    )
    return _inspection_result(store, job, completed)


def _verify_authoring_result(job, directory, result):
    roots = job["roots"]["write"]
    native = result["nativeSource"]
    recipe = result["recipe"]
    frames = result["frames"]
    if len(frames) != job["output"]["frameCount"]:
        raise ArtCraftError("ArtCraft output does not contain the selected frame count")
    references = [
        (native, directory / "component.anicraft"),
        (recipe, directory / "recipe.json"),
    ]
    references.extend(
        (frame, directory / "alpha" / f"frame_{index:05d}.png")
        for index, frame in enumerate(frames, 1)
    )
    if any(
        item["locator"] != str(path) or not _retained_job_file(item, roots)
        for item, path in references
    ):
        raise ArtCraftError(
            "ArtCraft returned output differs from the exact owned paths and fingerprints"
        )
    return {"saved": native, "recipe": recipe, "outputs": frames}


def _verify_retained_export(store, job, event):
    directory = (store.workspace / job["document"]).parent
    try:
        _verify_authoring_result(
            job,
            directory,
            {
                "nativeSource": event["saved"],
                "recipe": event["recipe"],
                "frames": event["outputs"],
            },
        )
    except (KeyError, ValueError) as exc:
        raise ArtCraftError(
            "ArtCraft retained export evidence is incomplete or stale",
            code="ARTCRAFT_SCOPE_CHANGED",
        ) from exc
