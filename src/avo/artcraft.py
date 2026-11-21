"""Records and coordination for optional ArtCraft authoring."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
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
    "describe_export_review",
    "guard_legacy_component_request",
    "inspect_authoring",
    "prepare_authoring",
    "prepare_authoring_reuse",
    "read_authoring_export",
    "recover_authoring",
    "require_artcraft_export_environment",
    "require_eligible",
    "retained_authoring_files",
    "run_authoring",
    "seal_record",
    "validate_record",
]

_SEALED = frozenset({"decision", "job", "event", "package", "receipt"})
_NATIVE_SUFFIXES = {
    "anicraft": ".anicraft",
    "soundcraft": ".scraft",
    "vectorcraft": ".vectorcraft",
    "filmcraft": ".fcproj",
    "photocraft": ".pcraft",
    "figcraft": ".figcraft",
}
_SOUND_CUE_SCOPE = {"app": "soundcraft", "operations": ["isolated-cue"]}
_STILL_CARD_SCOPE = {"app": "vectorcraft", "operations": ["vector-still"]}
_PHOTO_CARD_SCOPE = {"app": "photocraft", "operations": ["layered-image-card"]}
_FIG_VARIANT_SCOPE = {"app": "figcraft", "operations": ["editable-design-variant"]}
_STILL_SCOPES = (_STILL_CARD_SCOPE, _PHOTO_CARD_SCOPE, _FIG_VARIANT_SCOPE)
_VECTOR_EMBLEM_SCOPE = {"app": "vectorcraft", "operations": ["vector-emblem"]}
_ANIMATED_EMBLEM_SCOPE = {"app": "anicraft", "operations": ["animate-vector-emblem"]}
_FILM_RETURN_SCOPE = {
    "app": "filmcraft",
    "operations": ["source-linked-timeline-return"],
}
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
    if record.get("backend") == "artcraft" or {
        "artcraft",
        "nativePackage",
    }.intersection(record):
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
    _check_specialist_job(job, scope)


def _check_specialist_job(job, scope):
    if scope == _SOUND_CUE_SCOPE:
        _check_sound_job(job)
    if scope == _STILL_CARD_SCOPE:
        _require_still_contract(
            job["request"], job, job["documentState"], job["observation"]["mode"]
        )
    _check_photo_job(job, scope)
    _check_fig_job(job, scope)
    if scope == _FILM_RETURN_SCOPE:
        _check_film_job(job)
    if scope == _VECTOR_EMBLEM_SCOPE:
        _require_vector_emblem(
            job["request"], job, job["documentState"], job["observation"]["mode"]
        )
    if scope == _ANIMATED_EMBLEM_SCOPE:
        _require_animated_emblem(
            job["request"], job, job["documentState"], job["observation"]["mode"]
        )
    elif "artworkRef" in job:
        raise ContractError("Only the animated emblem may consume vector artwork")


def _check_photo_job(job, scope):
    if scope != _PHOTO_CARD_SCOPE:
        if "photoSource" in job:
            raise ContractError(
                "Only PhotoCraft layered-image-card may consume a photo"
            )
        return
    _require_photo_contract(
        job["request"], job, job["documentState"], job["observation"]["mode"]
    )
    if [item["locator"] for item in job["inputs"]] != [job["photoSource"]["source"]]:
        raise ContractError("PhotoCraft job requires its exact selected image")


def _check_fig_job(job, scope):
    if scope == _FIG_VARIANT_SCOPE:
        _require_fig_contract(
            job["request"], job, job["documentState"], job["observation"]["mode"]
        )


def _require_fig_contract(request, selected, document_state, mode):
    if (document_state, mode) != ("empty", "cli"):
        raise ArtCraftError("FigCraft requires an empty document and confined CLI mode")
    if (
        request["required"]
        != {
            "behavior": "editable-design-variant",
            "outputRole": "generated-still",
            "editable": True,
        }
        or selected["output"]
        != {
            "role": "generated-still",
            "format": "png",
            "alpha": "straight",
            "color": "srgb",
            "width": 320,
            "height": 180,
        }
        or selected.get("inputs")
        or {
            "authoringParameters",
            "soundCue",
            "interchangeSource",
            "photoSource",
        }.intersection(selected)
    ):
        raise ArtCraftError(
            "Select the editable FigCraft 320 × 180 design variant recipe"
        )


def _require_vector_emblem(request, configuration, document_state, mode):
    expected_output = {
        "role": "generated-still",
        "format": "svg",
        "width": 128,
        "height": 128,
        "alpha": "straight",
        "color": "srgb",
    }
    if (
        (document_state, mode) != ("empty", "cli")
        or request["required"]
        != {
            "behavior": "vector-emblem",
            "outputRole": "generated-still",
            "editable": True,
        }
        or configuration["output"] != expected_output
        or "authoringParameters" in configuration
        or configuration.get("inputs")
    ):
        raise ArtCraftError(
            "VectorCraft requires the editable 128 × 128 SVG emblem profile"
        )


def _require_animated_emblem(request, configuration, document_state, mode):
    output = configuration["output"]
    required = request["required"]
    if (
        (document_state, mode) != ("empty", "cli")
        or required
        != {
            "behavior": "animate-vector-emblem",
            "outputRole": "overlay-video",
            "editable": True,
        }
        or output
        != {
            "role": "overlay-video",
            "format": "png-sequence",
            "width": 320,
            "height": 180,
            "alpha": "straight",
            "color": "srgb",
            "frameRate": {"numerator": 24, "denominator": 1},
            "frameCount": 24,
        }
        or "artworkRef" not in configuration
        or {"authoringParameters", "interchangeSource", "soundCue"}.intersection(
            configuration
        )
    ):
        raise ArtCraftError(
            "Select an exact VectorCraft emblem export and the 320 × 180 motion profile"
        )


def _check_film_job(job):
    selected = job.get("interchangeSource")
    if (
        selected is None
        or len(job["inputs"]) != 1
        or job["inputs"][0]["locator"] != selected["source"]
    ):
        raise ContractError("FilmCraft job requires its exact selected original")
    if job["documentState"] != "empty" or job["observation"]["mode"] != "cli":
        raise ContractError(
            "FilmCraft job requires an empty document and confined CLI mode"
        )


def _check_sound_job(job):
    authored = job.get("soundCue")
    if authored is None or len(job["inputs"]) != 1 or job.get("authoringParameters"):
        raise ContractError("SoundCraft cue requires its selected input audio")
    if job["inputs"][0]["locator"] != authored["source"]:
        raise ContractError("SoundCraft source differs from the job's input lock")
    _require_sound_contract(
        job["request"], job["output"], job["documentState"], job["observation"]["mode"]
    )


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

    def _committed_operation(self, job, operation_id):
        directory = self._job_dir(job["jobId"])
        operation = self._index(directory)["operations"].get(operation_id)
        if operation is None:
            return None
        return self._indexed_event(directory, operation_id, operation, job["jobHash"])

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
    _require_preparation_profile(request, spec, scope)
    document = _owned_document(store, base, spec["jobId"], scope["app"])
    roots = _preparation_roots(spec, document.parent)
    source = _preparation_source(spec, roots, document)
    input_field, selected_input = _preparation_media(request, spec, scope, roots)
    dependencies = _prepared_artwork(request, spec, roots, scope)
    _require_preparation_capacity(
        store.workspace, spec["budget"], source or selected_input
    )
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
        "inputs": [item for item in (source, selected_input) if item is not None]
        + dependencies,
        "recipeHash": content_hash(recipe),
        "output": spec["output"],
        "budget": spec["budget"],
        **project_facts,
    }
    if authoring is not None:
        job["authoringParameters"] = authoring
    if selected_input is not None:
        job[input_field] = spec[input_field]
        job["recipeHash"] = content_hash([*recipe, spec[input_field], selected_input])
    if dependencies:
        job["artworkRef"] = spec["artworkRef"]
        job["recipeHash"] = content_hash([*recipe, job["artworkRef"], dependencies])
    return _publish_preparation(store, job, document, source)


def _require_preparation_profile(request, spec, scope):
    arguments = (request, spec, spec["document"]["state"], spec["mode"])
    if scope == _STILL_CARD_SCOPE:
        _require_still_contract(*arguments)
    if scope == _FIG_VARIANT_SCOPE:
        _require_fig_contract(*arguments)
    if scope == _VECTOR_EMBLEM_SCOPE:
        _require_vector_emblem(*arguments)
    if scope == _ANIMATED_EMBLEM_SCOPE:
        _require_animated_emblem(*arguments)
    elif "artworkRef" in spec:
        raise ArtCraftError(
            "Select AniCraft animate-vector-emblem to consume vector artwork"
        )


def _prepared_artwork(request, spec, roots, scope):
    if scope != _ANIMATED_EMBLEM_SCOPE:
        return []
    inputs = _artwork_export_inputs(request, spec["artworkRef"], roots)
    if inputs[0]["sizeBytes"] >= spec["budget"]["bytes"]:
        raise ArtCraftError("Vector artwork exceeds the selected motion budget")
    return inputs


def _artwork_export_inputs(request, reference, roots):
    read_roots = roots["read"]
    locator = reference["job"]["locator"]
    if not _retained_job_file(reference["job"], read_roots):
        raise ArtCraftError(
            "Vector artwork job must match its selected receipt and read roots"
        )
    store, job, event = _open_selected_job(locator, reference["exportHead"])
    if job["decision"]["scope"] != _VECTOR_EMBLEM_SCOPE or event["state"] != "exported":
        raise ArtCraftError(
            "Vector artwork requires the selected VectorCraft emblem export"
        )
    _require_artwork_owner(request, job["request"])
    require_artcraft_export_environment(job["observation"])
    if _inspection_result(store, job, event)["status"] != "current":
        raise ArtCraftError("The selected vector artwork evidence changed")
    _verify_retained_export(store, job, event)
    inputs = [event["outputs"][0], reference["job"], event["saved"], event["recipe"]]
    if not all(_retained_job_file(item, read_roots) for item in inputs):
        raise ArtCraftError(
            "Vector artwork and editable source must stay in the selected read roots"
        )
    return inputs


def _require_artwork_owner(request, upstream):
    if any(request[key] != upstream[key] for key in ("provider", "componentId")):
        raise ArtCraftError(
            "Vector artwork belongs to a different provider or component"
        )
    if (
        upstream["context"]["kind"] != "provider-only"
        and upstream["context"] != request["context"]
    ):
        raise ArtCraftError("Vector artwork belongs to a different video")


def prepare_authoring_reuse(request, spec, *, from_job, from_head, decision, intent):
    """Prepare a new video use of an exact previously rendered isolated component."""
    from types import SimpleNamespace

    require_eligible(request, decision, intent=intent)
    validate_document(spec, _schema("jobSpec"))
    if (
        spec["mode"] != "reuse"
        or spec["document"]["state"] != "saved"
        or {"cliPath", "appPath"}.intersection(spec)
    ):
        raise ArtCraftError(
            "ArtCraft reuse needs the saved source and the retained tool identity"
        )
    original, exported = _reusable_native_export(from_job, from_head)
    _require_reuse_match(request, spec, original)
    selected = {**original["inputs"][0], "locator": spec["document"]["source"]}
    if not _retained_job_file(selected, spec["readRoots"]):
        raise ArtCraftError(
            "ArtCraft reusable editable source differs from the selected source"
        )
    prior = original["observation"]
    observed = {
        **{
            key: prior[key]
            for key in (
                "app",
                "platform",
                "release",
                "operations",
                "executable",
                "application",
                "commandSchemaHash",
            )
        },
        "mode": "reuse",
        "reuseSource": {
            "jobRef": file_fingerprint(Path(from_job)),
            "exportHead": exported["eventHash"],
        },
    }
    return prepare_authoring(
        request,
        spec,
        decision=decision,
        intent=intent,
        adapter=SimpleNamespace(observe=lambda **_selection: observed),
    )


def _require_reuse_match(request, spec, original):
    if any(
        request.get(key) != original["request"][key]
        for key in ("provider", "componentId")
    ):
        raise ArtCraftError(
            "ArtCraft reusable export belongs to a different provider component"
        )
    if any(spec.get(key) != original[key] for key in ("output", "authoringParameters")):
        raise ArtCraftError(
            "ArtCraft selected parameters or output contract changed and needs rendering"
        )


def _reusable_native_export(job_ref, expected_head):
    store, job, event = _open_selected_job(job_ref, expected_head)
    observation = job["observation"]
    profile = (
        event["state"],
        job["documentState"],
        job["decision"]["scope"],
        observation["mode"],
    )
    expected = (
        "exported",
        "saved",
        {"app": "anicraft", "operations": ["lower-third"]},
        "cli",
    )
    if (
        profile != expected
        or not {"application", "executable", "commandSchemaHash"} <= observation.keys()
    ):
        raise ArtCraftError("Select a qualified native saved-source export for reuse")
    if (
        _inspect_job_inputs(job) != "current"
        or _inspect_job_document(store, job, event) != "current"
    ):
        raise ArtCraftError("ArtCraft reusable source or export changed")
    _verify_retained_export(store, job, event)
    for key in ("application", "executable"):
        expected = observation[key]
        if not _retained_job_file(expected, [str(Path(expected["locator"]).parent)]):
            raise ArtCraftError("ArtCraft reusable tool environment changed")
    return job, event


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


def _preparation_media(request, spec, scope, roots):
    if "photoSource" in spec or scope == _PHOTO_CARD_SCOPE:
        return "photoSource", _preparation_photo(request, spec, scope, roots)
    if "interchangeSource" in spec or scope == _FILM_RETURN_SCOPE:
        return "interchangeSource", _preparation_interchange(
            request, spec, scope, roots
        )
    return "soundCue", _preparation_audio(request, spec, scope, roots)


def _preparation_photo(request, spec, scope, roots):
    from .timeline.media_admission import FORBIDDEN_OUTPUT_CLASSES

    if scope != _PHOTO_CARD_SCOPE:
        raise ArtCraftError("Select PhotoCraft layered-image-card to consume a photo")
    _require_photo_contract(request, spec, spec["document"]["state"], spec["mode"])
    path = Path(spec["photoSource"]["source"])
    path = _bounded_path(_owning_root(path, roots["read"]), path, "PhotoCraft photo")
    if FORBIDDEN_OUTPUT_CLASSES.intersection(part.casefold() for part in path.parts):
        raise ArtCraftError("PhotoCraft cannot use a program proof or delivery")
    if (
        path.is_relative_to(roots["write"][0])
        or path.suffix.lower() != ".png"
        or not path.is_file()
    ):
        raise ArtCraftError("PhotoCraft requires one external original PNG")
    metadata = path.stat()
    if metadata.st_nlink != 1 or metadata.st_size >= spec["budget"]["bytes"]:
        raise ArtCraftError(
            "PhotoCraft photo must be unshared and within its byte budget"
        )
    return file_fingerprint(path)


def _require_photo_contract(request, spec, document_state, mode):
    output = spec["output"]
    if (
        request["required"]
        != {
            "behavior": "layered-image-card",
            "outputRole": "generated-still",
            "editable": True,
        }
        or (output["role"], output["format"], output.get("alpha"), output.get("color"))
        != ("generated-still", "png", "straight", "srgb")
        or not 240 <= output["width"] <= 1920
        or not 160 <= output["height"] <= 1920
    ):
        raise ArtCraftError(
            "Select one editable PhotoCraft RGBA PNG card within its canvas range"
        )
    if (
        (document_state, mode) != ("empty", "cli")
        or "photoSource" not in spec
        or {"authoringParameters", "interchangeSource", "soundCue"}.intersection(spec)
    ):
        raise ArtCraftError("Select an empty PhotoCraft CLI job and its original PNG")


def _preparation_interchange(request, spec, scope, roots):
    if scope != _FILM_RETURN_SCOPE or "soundCue" in spec:
        raise ArtCraftError("Select only the FilmCraft timeline interchange profile")
    if request["required"]["behavior"] != "source-linked-timeline-return":
        raise ArtCraftError("FilmCraft requires explicit source-linked timeline return")
    output = spec["output"]
    if (output["role"], output["format"]) != ("timeline-interchange", "otio"):
        raise ArtCraftError("FilmCraft return requires an OTIO timeline interchange")
    if spec["document"]["state"] != "empty" or spec["mode"] != "cli":
        raise ArtCraftError("Select an empty FilmCraft document and confined CLI mode")
    selected = spec.get("interchangeSource")
    if selected is None or "authoringParameters" in spec:
        raise ArtCraftError(
            "Select a fingerprinted original for the FilmCraft timeline"
        )
    return _film_source_fingerprint(Path(selected["source"]), roots, spec["budget"])


def _film_source_fingerprint(path, roots, budget):
    from .timeline.media_admission import FORBIDDEN_OUTPUT_CLASSES

    path = _bounded_path(_owning_root(path, roots["read"]), path, "FilmCraft original")
    if path.is_relative_to(roots["write"][0]) or path.suffix.lower() not in {
        ".mp4",
        ".mov",
    }:
        raise ArtCraftError("FilmCraft requires an external original MP4 or MOV")
    if FORBIDDEN_OUTPUT_CLASSES.intersection(part.casefold() for part in path.parts):
        raise ArtCraftError(
            "FilmCraft cannot use a program proof or delivery as its original"
        )
    if (
        not path.is_file()
        or path.stat().st_nlink != 1
        or path.stat().st_size >= budget["bytes"]
    ):
        raise ArtCraftError(
            "FilmCraft original must be an unshared file within the byte budget"
        )
    return file_fingerprint(path)


def _preparation_audio(request, spec, scope, roots):
    selected = spec.get("soundCue")
    if scope != _SOUND_CUE_SCOPE:
        if selected is not None:
            raise ArtCraftError("Select SoundCraft isolated-cue for a sound cue")
        return None
    if selected is None:
        raise ArtCraftError("Select a source WAV and a SoundCraft room reverb")
    if "authoringParameters" in spec:
        raise ArtCraftError("Select only the SoundCraft cue parameters")
    _require_sound_contract(
        request, spec["output"], spec["document"]["state"], spec["mode"]
    )
    path = Path(selected["source"])
    root = _owning_root(path, roots["read"])
    path = _bounded_path(root, path, "sound cue source")
    if path.is_relative_to(roots["write"][0]) or path.suffix != ".wav":
        raise ArtCraftError("SoundCraft cue needs one external source WAV")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ArtCraftError("SoundCraft cue source must be one regular unshared file")
    if path.stat().st_size >= spec["budget"]["bytes"]:
        raise ArtCraftError("SoundCraft cue source exceeds the selected byte budget")
    return file_fingerprint(path)


def _require_sound_contract(request, output, document_state, mode):
    shape = (
        output["role"],
        output["format"],
        output.get("sampleRate"),
        output.get("channels"),
    )
    if (
        shape != ("generated-audio", "wav", 48000, 2)
        or output.get("sampleCount", 0) > 480000
    ):
        raise ArtCraftError(
            "SoundCraft cue needs a 48 kHz stereo WAV of up to ten seconds"
        )
    if request["required"]["behavior"] != "editable-isolated-cue":
        raise ArtCraftError(
            "SoundCraft cue requires the selected editable cue behavior"
        )
    if document_state != "empty" or mode != "cli":
        raise ArtCraftError(
            "Select a blank SoundCraft document and the confined CLI mode"
        )


def _require_still_contract(request, selected, document_state, mode):
    if request["required"]["behavior"] != "editable-vector-card":
        raise ArtCraftError(
            "VectorCraft card requires the explicit editable-vector-card behavior"
        )
    output = selected["output"]
    shape = {key: output.get(key) for key in ("role", "format", "alpha", "color")}
    if shape != {
        "role": "generated-still",
        "format": "png",
        "alpha": "straight",
        "color": "srgb",
    }:
        raise ArtCraftError("VectorCraft card requires a straight-alpha sRGB PNG still")
    if not 240 <= output["width"] <= 1920 or not 160 <= output["height"] <= 1920:
        raise ArtCraftError("VectorCraft card is outside its supported canvas range")
    if (
        document_state != "empty"
        or mode != "cli"
        or "authoringParameters" not in selected
    ):
        raise ArtCraftError(
            "Select a blank VectorCraft CLI job and explicit card text and font"
        )


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
    if spec["mode"] == "reuse":
        authority = bool(observation.get("reuseSource"))
    elif spec["mode"] in {"guided", "host-mcp"}:
        authority = observation.get("authority") == "operator"
    else:
        authority = observation.get("effectiveRoots") == roots
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


def inspect_authoring(job_ref, *, expected_head, source_inspector=None):
    """Reconcile retained job evidence without changing files or starting an app."""
    store, job, head = _open_selected_job(job_ref, expected_head)
    result = _inspection_result(store, job, head)
    if result["status"] == "stale":
        result["changes"] = _describe_authoring_changes(
            job, head, result["checks"], source_inspector
        )
        return result
    if (
        source_inspector is not None
        and result["checks"]["nativeDocument"] == "returned-unverified"
    ):
        native = store.workspace / job["document"]
        result["sourceObservations"] = source_inspector(job, native)
    return result


def _describe_authoring_changes(job, head, checks, source_inspector):
    roots = job["roots"]
    targets = _recorded_authoring_files(job, head)
    actions = {
        "project": ["revalidate-placement", "review-proof-context"],
        "inputs": ["rebuild-from-current-inputs", "review-native-design"],
        "nativeDocument": ["author-new-revision", "review-native-design"],
        "outputs": ["rebuild-export", "review-export"],
        "handoff": ["reconcile-operator-handoff"],
    }
    changes = []
    for area, required in actions.items():
        if checks.get(area) != "changed":
            continue
        files = [
            item
            for item in targets[area]
            if item and not _retained_job_file(item, roots["read"])
        ]
        change = {"area": area, "recordedFiles": files, "actions": required}
        if area == "nativeDocument" and files:
            parameters = _inspect_edited_parameters(job, files[0], source_inspector)
            if parameters:
                change["parameterChanges"] = parameters
        changes.append(change)
    return changes


def _recorded_authoring_files(job, head):
    prior = []
    if job.get("documentState") == "saved" and job["inputs"]:
        owned_source = Path(job["workspace"]) / job["document"]
        prior = [{**job["inputs"][0], "locator": str(owned_source)}]
    return {
        "project": [],  # Project or canonical revisions may have changed.
        "inputs": job["inputs"],
        "nativeDocument": [head.get("saved"), *prior],
        "outputs": [
            head.get("recipe"),
            *head.get("outputs", []),
            *head.get("dependencies", []),
        ],
        "handoff": [head.get("handoff")],
    }


def retained_authoring_files(job_ref, *, expected_head=None):
    """Return exact local and external files needed to retain a native job."""
    store, job, head = _selected_job(job_ref)
    if expected_head is not None and (head["eventHash"], head["state"]) != (
        expected_head,
        "exported",
    ):
        raise _changed_job_head()
    roots = job["roots"]
    declared = _recorded_authoring_files(job, head)
    owned = [
        *declared["nativeDocument"],
        *declared["outputs"],
        *declared["handoff"],
        *head.get("partialFiles", []),
    ]
    _require_retained_artifacts(declared["inputs"], roots["read"])
    _require_retained_artifacts(owned, roots["write"])
    return job, [
        *_retained_job_records(store, job, head),
        *declared["inputs"],
        *(item for item in owned if item),
    ]


def _require_retained_artifacts(references, roots):
    for reference in references:
        if reference is not None and not _retained_job_file(reference, roots):
            raise ArtCraftError(
                f"Retained ArtCraft file changed or is missing: {reference['locator']}"
            )


def _retained_job_records(store, job, head):
    directory = store.reference(job["jobId"]).parent
    index_path = store._index_path(directory)
    index_fingerprint = file_fingerprint(index_path)
    index = store._index(directory)
    if index["operations"].get(index["head"]) != head["eventHash"]:
        raise _changed_job_head()
    records = [file_fingerprint(store.reference(job["jobId"])), index_fingerprint]
    predecessors = {}
    for operation, event_hash in index["operations"].items():
        event = store._indexed_event(directory, operation, event_hash, job["jobHash"])
        predecessors[event_hash] = event["predecessorHash"]
        records.append(file_fingerprint(directory / f"event-{operation}.json"))
    _require_retained_job_chain(head["eventHash"], predecessors)
    if file_fingerprint(index_path) != index_fingerprint:
        raise _changed_job_head()
    return records


def _require_retained_job_chain(head_hash, predecessors):
    while head_hash is not None:
        if head_hash not in predecessors:
            raise ArtCraftError(
                "Retained ArtCraft journal has an incomplete event chain"
            )
        head_hash = predecessors.pop(head_hash)
    if predecessors:
        raise ArtCraftError("Retained ArtCraft journal has an unrelated event")


def _inspect_edited_parameters(job, reference, source_inspector):
    parameters = job.get("authoringParameters")
    scope = job["decision"]["scope"]
    if (
        not parameters
        or source_inspector is None
        or scope != {"app": "anicraft", "operations": ["lower-third"]}
    ):
        return []
    path = Path(reference["locator"])
    owned = Path(job["workspace"]) / job["document"]
    if path not in {owned, owned.parent / "revision" / owned.name}:
        return []
    try:
        _bounded_path(
            _owning_root(path, job["roots"]["write"]), path, "edited native document"
        )
        observed = source_inspector({**job, "authoringParameters": None}, path)
    except (OSError, ValueError, RuntimeError):
        return []
    return [
        {"name": field, "recorded": parameters[field], "observed": observed[name]}
        for field, name in (("primaryText", "editableText"), ("font", "fontFamily"))
        if observed.get(name) is not None and observed[name] != parameters[field]
    ]


def recover_authoring(job_ref, *, expected_head, action="inspect", adapter=None):
    """Inspect retained evidence or explicitly retry or cancel an unstarted job."""
    if action == "retry":
        return run_authoring(job_ref, expected_head=expected_head, adapter=adapter)
    if action == "cancel":
        return _cancel_prepared_authoring(job_ref, expected_head)
    if action != "inspect":
        raise ArtCraftError(
            "Select inspect, retry, or cancel to recover the ArtCraft job"
        )
    return _summarize_recovery(job_ref, expected_head)


def _cancel_prepared_authoring(job_ref, expected_head):
    store, _, head = _selected_job(job_ref)
    _require_cancel_head(head, expected_head)
    with store.writer():
        _, job, head = _selected_job(job_ref)
        _require_cancel_head(head, expected_head)
        result = _inspection_result(store, job, head)
        if head["state"] == "cancelled":
            return result
        if result["status"] != "current":
            raise _changed_job_head()
        event = store.append(
            job["jobId"],
            expected_head=expected_head,
            event={"operationId": "cancel", "state": "cancelled"},
        )
        return _inspection_result(store, job, event)


def _require_cancel_head(head, expected_head):
    if (head["operationId"], head["state"]) == (
        "cancel",
        "cancelled",
    ) and expected_head in {head["eventHash"], head["predecessorHash"]}:
        return
    if head["eventHash"] != expected_head:
        raise _changed_job_head()
    if head["state"] == "ready":
        raise ArtCraftError(
            "Reconcile the operator-owned ArtCraft handoff before cancellation",
            code="ARTCRAFT_OWNERSHIP_CONFLICT",
        )
    if head["state"] in {"running", "cancel-requested", "outcome-unknown"}:
        raise ArtCraftError(
            "Reconcile the active ArtCraft writer before cancellation",
            code="ARTCRAFT_OUTCOME_UNKNOWN",
        )
    if head["state"] != "prepared":
        raise ArtCraftError(
            "ArtCraft cancellation requires an unstarted job",
            code="ARTCRAFT_NOT_ELIGIBLE",
        )


def _summarize_recovery(job_ref, expected_head):
    store, job, head = _open_selected_job(job_ref, expected_head)
    result = _inspection_result(store, job, head)
    state = head["state"]
    if state == "exported" and result["status"] == "current":
        _verify_retained_export(store, job, head)
        return {
            **result,
            "recovery": {
                "nextAction": "use-verified-export",
                "outputs": head["outputs"],
            },
        }
    actions = {
        "prepared": "run-prepared-job",
        "ready": "inspect-operator-return",
        "running": "inspect-current-owner",
        "cancelled": "keep-cancelled",
    }
    action = actions.get(state, "prepare-fresh-job")
    if result["status"] == "stale" and state in {"prepared", "ready", "exported"}:
        action = "restore-selected-inputs"
    return {
        **result,
        "recovery": {
            "nextAction": action,
            "artifactState": "reference-only",
            **_recovery_files(job, _authoring_export_directory(store, job), head),
        },
    }


def _recovery_files(job, directory, head):
    files = _recoverable_job_files(job, directory)
    locked = head.get("partialFiles")
    if locked is None:
        return {"retainedFiles": files}
    by_locator = {item["locator"]: item for item in files}
    retained, changed = [], []
    for fingerprint in locked:
        matches = by_locator.get(fingerprint["locator"]) == fingerprint
        (retained if matches else changed).append(fingerprint)
    return {"retainedFiles": retained, "changedPartialFiles": changed}


def _recoverable_job_files(job, directory):
    budget = job["budget"]
    count = min(job["output"].get("frameCount", 0), budget["files"])
    names = {
        "soundcraft": (
            "component.scraft",
            "recipe.json",
            "cue.wav",
            "Audio Files/source.wav",
        ),
        "vectorcraft": (
            "component.vectorcraft",
            "recipe.json",
            "card.png",
            "emblem.svg",
        ),
        "filmcraft": ("component.fcproj", "recipe.json", "component.otio"),
    }.get(
        job["decision"]["scope"]["app"],
        ("component.anicraft", "recipe.json", "handoff.json"),
    )
    candidates = [directory / name for name in names]
    candidates.extend(
        directory / "alpha" / f"frame_{index:05d}.png" for index in range(1, count + 1)
    )
    observed, used = [], 0
    for path in candidates[: budget["files"]]:
        fingerprint = _recoverable_file(path, budget["bytes"] - used)
        if fingerprint is None:
            continue
        observed.append(fingerprint)
        used += fingerprint["sizeBytes"]
    return observed


def _recoverable_file(path, remaining):
    try:
        if path.resolve() != path or not path.is_file():
            return None
        metadata = path.stat()
        if metadata.st_nlink != 1 or metadata.st_size > remaining:
            return None
        fingerprint = file_fingerprint(path)
        if fingerprint["sizeBytes"] == metadata.st_size:
            return fingerprint
    except (OSError, RuntimeError):
        return None
    return None


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
    store, job, head = _selected_job(job_ref)
    if head["eventHash"] != expected_head:
        raise _changed_job_head()
    return store, job, head


def _changed_job_head():
    return ArtCraftError(
        "ArtCraft expected job event head changed or is missing",
        code="ARTCRAFT_SCOPE_CHANGED",
    )


def _selected_job(job_ref):
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
    if stored != record or head is None:
        raise _changed_job_head()
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


def require_artcraft_export_environment(observation):
    """Check the current selected tool bytes without probing or launching an app."""
    if observation["mode"] not in {"cli", "reuse"} or not observation.get(
        "commandSchemaHash"
    ):
        raise ArtCraftError(
            "ArtCraft export needs independent native command observations",
            code="ARTCRAFT_ADMISSION_REQUIRED",
        )
    try:
        _verify_selected_binary(observation["application"])
        _verify_selected_binary(observation["executable"])
    except (KeyError, OSError, ValueError) as exc:
        raise ArtCraftError(
            "ArtCraft selected installation has changed or is incomplete",
            code="ARTCRAFT_SCOPE_CHANGED",
        ) from exc
    return observation


def _verify_selected_binary(fingerprint):
    path = Path(fingerprint["locator"])
    if (
        not path.is_absolute()
        or path.resolve() != path
        or file_fingerprint(path) != fingerprint
    ):
        raise ArtCraftError("ArtCraft selected native tool fingerprint changed")


def _owning_root(path, roots):
    for root in map(Path, roots):
        if root.is_absolute() and path.is_relative_to(root):
            return root
    raise ArtCraftError("ArtCraft evidence falls outside the approved roots")


def _inspect_job_inputs(job):
    if "artworkRef" in job:
        try:
            inputs = _artwork_export_inputs(
                job["request"], job["artworkRef"], job["roots"]
            )
        except (OSError, ValueError, RuntimeError):
            return "changed"
        return "current" if inputs == job["inputs"] else "changed"
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
    expected = [*expected, *head.get("dependencies", [])]
    return (
        "current"
        if all(_retained_job_file(item, job["roots"]["write"]) for item in expected)
        else "changed"
    )


def _inspect_job_document(store, job, head):
    path = store.workspace / job["document"]
    roots = job["roots"]["write"]
    saved = head.get("saved")
    if job.get("documentState") == "saved":
        if not job["inputs"] or not _retained_job_file(
            {**job["inputs"][0], "locator": str(path)}, roots
        ):
            return "changed"
        if saved is None:
            return "current"
        path = _authoring_export_directory(store, job) / "component.anicraft"
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
    store, job, head = _selected_job(job_ref)
    _require_current_or_replayed_authoring(store, job, head, expected_head)
    with store.writer():
        _, job, head = _selected_job(job_ref)
        _require_current_or_replayed_authoring(store, job, head, expected_head)
        if head["state"] in {"running", "outcome-unknown", "cancel-requested"}:
            raise ArtCraftError(
                "ArtCraft job requires reconciliation before another operation",
                code="ARTCRAFT_OUTCOME_UNKNOWN",
                remediation=f"Inspect the retained job at head {head['eventHash']} before attempting recovery.",
            )
        inspection = _inspection_result(store, job, head)
        if inspection["status"] != "current":
            raise ArtCraftError(
                "ArtCraft prepared job is stale", code="ARTCRAFT_SCOPE_CHANGED"
            )
        if head["state"] == "exported":
            _verify_retained_export(store, job, head)
            return inspection
        if job["observation"]["mode"] in {"guided", "host-mcp"}:
            return _run_operator_handoff(store, job, head, inspection, adapter)
        directory = _require_prepared_authoring(store, job, head)
        if job["observation"]["mode"] == "reuse":
            produce = _copy_reusable_export
        else:
            adapter.validate_run(job)
            produce = _select_job_author(adapter, job["decision"]["scope"])
        running = store.append(
            job["jobId"],
            expected_head=expected_head,
            event={"operationId": "run", "state": "running"},
        )
    return _execute_prepared_job(store, job, running, directory, produce)


def _require_current_or_replayed_authoring(store, job, head, expected_head):
    if head["eventHash"] == expected_head:
        return
    outcome = head["operationId"], head["state"]
    if (
        outcome in {("run", "running"), ("guide", "ready")}
        and head["predecessorHash"] == expected_head
    ):
        return
    if outcome in {("verify-run", "exported"), ("reconcile-run", "outcome-unknown")}:
        running = store._committed_operation(job, "run")
        if running is not None and (
            running["state"],
            running["predecessorHash"],
            running["eventHash"],
        ) == ("running", expected_head, head["predecessorHash"]):
            return
    raise _changed_job_head()


def _select_job_author(adapter, scope):
    if scope == _FILM_RETURN_SCOPE:
        return adapter.author_film_interchange
    if scope == _SOUND_CUE_SCOPE:
        return adapter.author_isolated_cue
    if scope == _STILL_CARD_SCOPE:
        return adapter.author_vector_card
    if scope == _PHOTO_CARD_SCOPE:
        return adapter.author_photo_card
    if scope == _FIG_VARIANT_SCOPE:
        return adapter.author_fig_variant
    if scope == _VECTOR_EMBLEM_SCOPE:
        return adapter.author_vector_emblem
    if scope == _ANIMATED_EMBLEM_SCOPE:
        return adapter.author_animated_emblem
    return adapter.author_lower_third


def _copy_reusable_export(job, directory):
    selected = job["observation"]["reuseSource"]
    prior_ref = Path(selected["jobRef"]["locator"])
    if file_fingerprint(prior_ref) != selected["jobRef"]:
        raise ArtCraftError("ArtCraft retained reuse receipt changed")
    prior, exported = _reusable_native_export(prior_ref, selected["exportHead"])
    _require_reuse_match(job["request"], job, prior)
    expected = {**prior["inputs"][0], "locator": job["inputs"][0]["locator"]}
    if job["inputs"][0] != expected:
        raise ArtCraftError(
            "ArtCraft prepared editable source differs from the reusable source"
        )
    native = directory / "component.anicraft"
    recipe = directory / "recipe.json"
    frames = [
        directory / "alpha" / f"frame_{number:05d}.png"
        for number in range(1, len(exported["outputs"]) + 1)
    ]
    sources = [exported["saved"], exported["recipe"], *exported["outputs"]]
    budget = job["budget"]
    if (
        len(sources) > budget["files"]
        or sum(item["sizeBytes"] for item in sources) > budget["bytes"]
    ):
        raise ArtCraftError(
            "ArtCraft retained output exceeds the selected reuse budget"
        )
    directory.mkdir()
    deadline = monotonic() + budget["seconds"]
    for target, fingerprint in zip([native, recipe, *frames], sources, strict=True):
        if monotonic() >= deadline:
            raise ArtCraftError(
                "ArtCraft retained output exceeded its reuse time budget"
            )
        _copy_native_source(target, fingerprint)
    return {
        "nativeSource": file_fingerprint(native),
        "recipe": file_fingerprint(recipe),
        "frames": [file_fingerprint(path) for path in frames],
        "revisionCommandSchemaHash": exported["revisionCommandSchemaHash"],
    }


def _run_operator_handoff(store, job, head, inspection, adapter):
    if job["documentState"] == "saved":
        raise ArtCraftError(
            "Selected saved-source revisions require a qualified confined CLI runner",
            code="ARTCRAFT_NOT_READY",
        )
    if head["state"] == "ready" and inspection["checks"].get("handoff") == "current":
        return inspection
    directory = _require_prepared_authoring(store, job, head)
    plan = adapter.plan_lower_third(job, directory)
    directory.mkdir(parents=True, exist_ok=True)
    recipe = _bounded_path(directory, directory / "recipe.json", "operator recipe")
    write_immutable_json(recipe, plan["steps"])
    handoff = _bounded_path(directory, directory / "handoff.json", "operator handoff")
    write_immutable_json(
        handoff,
        {
            "version": 1,
            "jobHash": job["jobHash"],
            "mode": job["observation"]["mode"],
            "artifactState": "reference-only",
            "operatorRoots": job["roots"],
            "nativeDocument": str(directory / "component.anicraft"),
            "recipe": file_fingerprint(recipe),
            "commands": plan["commands"],
            **(
                {"host": plan["host"], "operatorBudget": job["budget"]}
                if "host" in plan
                else {}
            ),
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


def _require_prepared_authoring(store, job, head):
    if head["state"] == "cancelled":
        raise ArtCraftError(
            "ArtCraft job was cancelled before launch", code="ARTCRAFT_NOT_ELIGIBLE"
        )
    if head["state"] != "prepared":
        raise ArtCraftError(
            "ArtCraft job requires reconciliation before another operation",
            code="ARTCRAFT_OUTCOME_UNKNOWN",
        )
    scope = job["decision"]["scope"]
    if scope not in (
        _SOUND_CUE_SCOPE,
        _STILL_CARD_SCOPE,
        _PHOTO_CARD_SCOPE,
        _FIG_VARIANT_SCOPE,
        _FILM_RETURN_SCOPE,
        _VECTOR_EMBLEM_SCOPE,
        _ANIMATED_EMBLEM_SCOPE,
    ) and (
        scope != {"app": "anicraft", "operations": ["lower-third"]}
        or not job.get("authoringParameters")
    ):
        raise ArtCraftError(
            "ArtCraft runner needs the selected AniCraft lower-third parameters",
            code="ARTCRAFT_NOT_ELIGIBLE",
        )
    directory = store.workspace / job["document"]
    if job["roots"]["write"] != [str(directory.parent)]:
        raise ArtCraftError(
            "ArtCraft job output does not match the verified write root",
            code="ARTCRAFT_SCOPE_CHANGED",
        )
    return _bounded_path(
        store.workspace, _authoring_export_directory(store, job), "job output"
    )


def _authoring_export_directory(store, job):
    directory = (store.workspace / job["document"]).parent
    return directory / "revision" if job["documentState"] == "saved" else directory


def _execute_prepared_job(store, job, running, directory, produce):
    try:
        result = produce(job, directory)
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
            event={
                "operationId": "reconcile-run",
                "state": "outcome-unknown",
                "partialFiles": _recoverable_job_files(job, directory),
            },
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
    if job["decision"]["scope"] == _FILM_RETURN_SCOPE:
        return _verify_film_authoring_result(job, directory, result)
    if job["decision"]["scope"] == _SOUND_CUE_SCOPE:
        return _verify_sound_authoring_result(job, directory, result)
    if job["decision"]["scope"] in _STILL_SCOPES:
        return _verify_still_authoring_result(job, directory, result)
    if job["decision"]["scope"] == _VECTOR_EMBLEM_SCOPE:
        return _verify_emblem_authoring_result(job, directory, result)
    return _verify_sequence_authoring_result(job, directory, result)


def _verify_emblem_authoring_result(job, directory, result):
    retained = (
        (result["nativeSource"], directory / "component.vectorcraft"),
        (result["recipe"], directory / "recipe.json"),
        (result["media"], directory / "emblem.svg"),
    )
    if any(
        evidence["locator"] != str(path)
        or not _retained_job_file(evidence, job["roots"]["write"])
        for evidence, path in retained
    ):
        raise ArtCraftError("VectorCraft emblem evidence differs from its owned files")
    return {
        "saved": result["nativeSource"],
        "recipe": result["recipe"],
        "outputs": [result["media"]],
    }


def _verify_sequence_authoring_result(job, directory, result):
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
    evidence = {"saved": native, "recipe": recipe, "outputs": frames}
    if job["documentState"] == "saved":
        digest = result.get("revisionCommandSchemaHash")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ArtCraftError(
                "ArtCraft saved revision needs observed native edit commands"
            )
        evidence["revisionCommandSchemaHash"] = digest
    return evidence


def _verify_sound_authoring_result(job, directory, result):
    native, recipe, media = (result[key] for key in ("nativeSource", "recipe", "media"))
    dependencies = result["dependencies"]
    evidence = result["audioEvidence"]
    validate_document(evidence, _schema("audioEvidence"))
    expected_clock = tuple(
        job["output"][key] for key in ("sampleRate", "sampleCount", "channels")
    )
    clock = tuple(evidence[key] for key in ("sampleRate", "sampleCount", "channels"))
    if clock != expected_clock or len(dependencies) != 1:
        raise ArtCraftError(
            "SoundCraft output clock or retained audio dependency changed"
        )
    paths = (
        (native, directory / "component.scraft"),
        (recipe, directory / "recipe.json"),
        (media, directory / "cue.wav"),
        (dependencies[0], directory / "Audio Files" / "source.wav"),
    )
    roots = job["roots"]["write"]
    if any(
        item["locator"] != str(path) or not _retained_job_file(item, roots)
        for item, path in paths
    ):
        raise ArtCraftError("SoundCraft output is outside the owned cue or changed")
    if media["sha256"] == job["inputs"][0]["sha256"]:
        raise ArtCraftError(
            "SoundCraft cannot relabel its original input as a generated cue"
        )
    return {
        "saved": native,
        "recipe": recipe,
        "outputs": [media],
        "dependencies": dependencies,
        "audioEvidence": evidence,
    }


def _verify_still_authoring_result(job, directory, result):
    evidence = result["stillEvidence"]
    validate_document(evidence, _schema("stillEvidence"))
    expected = {
        key: job["output"][key]
        for key in ("width", "height", "format", "color", "alpha")
    }
    if any(evidence[key] != value for key, value in expected.items()):
        raise ArtCraftError("ArtCraft still evidence differs from the selected canvas")
    app = job["decision"]["scope"]["app"]
    still_name = {
        "vectorcraft": "card.png",
        "photocraft": "photo.png",
        "figcraft": "design.png",
    }[app]
    target_paths = {
        "nativeSource": directory / ("component" + _NATIVE_SUFFIXES[app]),
        "recipe": directory / "recipe.json",
        "media": directory / still_name,
    }
    for key, path in target_paths.items():
        item = result[key]
        if item["locator"] != str(path) or not _retained_job_file(
            item, job["roots"]["write"]
        ):
            raise ArtCraftError(
                "ArtCraft still must use the exact retained output files"
            )
    return {
        "saved": result["nativeSource"],
        "recipe": result["recipe"],
        "outputs": [result["media"]],
        "stillEvidence": evidence,
    }


def _verify_film_authoring_result(job, directory, result):
    evidence = result["interchangeEvidence"]
    validate_document(evidence, _schema("interchangeEvidence"))
    for key, name in (
        ("nativeSource", "component.fcproj"),
        ("recipe", "recipe.json"),
        ("media", "component.otio"),
    ):
        item = result[key]
        if item["locator"] != str(directory / name) or not _retained_job_file(
            item, job["roots"]["write"]
        ):
            raise ArtCraftError(
                "FilmCraft interchange differs from its owned job artifacts"
            )
    return {
        "saved": result["nativeSource"],
        "recipe": result["recipe"],
        "outputs": [result["media"]],
        "interchangeEvidence": evidence,
    }


def _verify_retained_export(store, job, event):
    directory = _authoring_export_directory(store, job)
    try:
        media_evidence = {}
        if job["decision"]["scope"] == _SOUND_CUE_SCOPE:
            (media,) = event["outputs"]
            media_evidence = {
                "media": media,
                "dependencies": event["dependencies"],
                "audioEvidence": event["audioEvidence"],
            }
        if job["decision"]["scope"] in _STILL_SCOPES:
            (media,) = event["outputs"]
            media_evidence = {"media": media, "stillEvidence": event["stillEvidence"]}
        if job["decision"]["scope"] == _FILM_RETURN_SCOPE:
            (media,) = event["outputs"]
            media_evidence = {
                "media": media,
                "interchangeEvidence": event["interchangeEvidence"],
            }
        if job["decision"]["scope"] == _VECTOR_EMBLEM_SCOPE:
            (media,) = event["outputs"]
            media_evidence = {"media": media}
        _verify_authoring_result(
            job,
            directory,
            {
                "nativeSource": event["saved"],
                "recipe": event["recipe"],
                "frames": event["outputs"],
                "revisionCommandSchemaHash": event.get("revisionCommandSchemaHash"),
                **media_evidence,
            },
        )
    except (KeyError, ValueError) as exc:
        raise ArtCraftError(
            "ArtCraft retained export evidence is incomplete or stale",
            code="ARTCRAFT_SCOPE_CHANGED",
        ) from exc


def read_authoring_export(job_ref, *, expected_head):
    """Read the exact exported native job after rechecking its retained files."""
    store, job, event = _open_selected_job(job_ref, expected_head)
    if event["state"] != "exported":
        raise ArtCraftError(
            "ArtCraft needs a verified rendered export",
            code="ARTCRAFT_ADMISSION_REQUIRED",
        )
    current = _inspection_result(store, job, event)
    if current["status"] != "current":
        raise ArtCraftError(
            "ArtCraft export evidence is stale", code="ARTCRAFT_SCOPE_CHANGED"
        )
    _verify_retained_export(store, job, event)
    return job, event


def _describe_still_review(job, event, job_ref):
    standalone = {
        "still": event["outputs"][0],
        "stillEvidence": event["stillEvidence"],
    }
    if job["decision"]["scope"] == _STILL_CARD_SCOPE:
        standalone["generatedStillRef"] = {
            "job": file_fingerprint(Path(job_ref)),
            "exportHead": event["eventHash"],
        }
    else:
        standalone["admission"] = "standalone-review"
    if job["decision"]["scope"] == _FIG_VARIANT_SCOPE:
        standalone["losses"] = [
            "The PNG holds a single static variant. The editable layout and click-to-switch prototype remain in the native design."
        ]
    return {
        "reviewState": "pending-creator",
        "jobHash": job["jobHash"],
        "exportHead": event["eventHash"],
        "componentId": job["request"]["componentId"],
        "viewerPurpose": job["request"]["purpose"],
        "nativeSource": event["saved"],
        "outputContract": job["output"],
        "standalone": standalone,
    }


def describe_export_review(job_ref, *, expected_head):
    """Describe the exact standalone candidate for an independent creator review."""
    job, event = read_authoring_export(job_ref, expected_head=expected_head)
    if job["decision"]["scope"] == _VECTOR_EMBLEM_SCOPE:
        return {
            "reviewState": "pending-creator",
            "jobHash": job["jobHash"],
            "exportHead": expected_head,
            "nativeSource": event["saved"],
            "outputContract": job["output"],
            "standalone": {
                "vectorArtwork": event["outputs"][0],
                "artworkRef": {
                    "job": file_fingerprint(Path(job_ref)),
                    "exportHead": expected_head,
                },
            },
        }
    if job["decision"]["scope"] == _FILM_RETURN_SCOPE:
        return {
            "reviewState": "pending-creator",
            "jobHash": job["jobHash"],
            "exportHead": expected_head,
            "nativeSource": event["saved"],
            "outputContract": job["output"],
            "standalone": {
                "timeline": event["outputs"][0],
                **event["interchangeEvidence"],
            },
        }
    if job["decision"]["scope"] in _STILL_SCOPES:
        return _describe_still_review(job, event, job_ref)
    if job["decision"]["scope"] == _SOUND_CUE_SCOPE:
        reference = {
            "job": file_fingerprint(Path(job_ref)),
            "exportHead": expected_head,
        }
        return {
            "reviewState": "pending-creator",
            "jobHash": job["jobHash"],
            "exportHead": event["eventHash"],
            "componentId": job["request"]["componentId"],
            "viewerPurpose": job["request"]["purpose"],
            "nativeSource": event["saved"],
            "outputContract": job["output"],
            "standalone": {
                "audio": event["outputs"][0],
                "audioEvidence": event["audioEvidence"],
                "dependencies": event["dependencies"],
                "generatedAudioRef": reference,
                "sourceId": "artcraft-audio-" + content_hash(reference)[:24],
            },
        }
    if job["decision"]["scope"] not in (
        _ANIMATED_EMBLEM_SCOPE,
        {"app": "anicraft", "operations": ["lower-third"]},
    ):
        raise ArtCraftError("The selected job has no qualified review profile")
    count = job["output"]["frameCount"]
    phases = {
        "before": 0,
        "entrance": count // 8,
        "hold": count // 3,
        "exit": 7 * count // 8,
        "after": count - 1,
    }
    return {
        "reviewState": "pending-creator",
        "jobHash": job["jobHash"],
        "exportHead": event["eventHash"],
        "componentId": job["request"]["componentId"],
        "viewerPurpose": job["request"]["purpose"],
        "editableBehavior": job["request"]["required"]["behavior"],
        "nativeSource": event["saved"],
        "outputContract": job["output"],
        **({"artworkRef": job["artworkRef"]} if "artworkRef" in job else {}),
        "standalone": {
            "frames": [
                {"phase": phase, "localFrame": frame, "output": event["outputs"][frame]}
                for phase, frame in phases.items()
            ],
            "checks": [
                "initial and final transparency",
                "entrance and exit timing",
                "readable hold at mobile size",
                "contrast on light, dark and busy footage",
            ],
        },
    }
