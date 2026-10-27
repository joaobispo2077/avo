"""Validated motion choices and framework-independent composition contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sys
from copy import deepcopy
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from avo.paths import repo_root, schemas_dir
from avo.settings import resolve_scoped_settings
from avo.timeline.contracts import (
    ContractError,
    content_hash,
    document_hash_excluding,
    file_fingerprint,
    validate_document,
)
from avo.timeline.store import atomic_write_json

ENGINE_IDS = ("hyperframes", "remotion", "code-drawn")
DEFAULT_ENGINE = "hyperframes"
MAX_CAPTURE_PIXELS = 33_554_432


class MotionError(ValueError):
    """An actionable motion choice or source-contract failure."""

    def __init__(
        self, code: str, message: str, *, field: str = "", remediation: str = ""
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.remediation = remediation or "Repair the specified motion input and retry."

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "field": self.field,
            "remediation": self.remediation,
            "blocking": True,
        }


def validate_engine(value: Any) -> str:
    if not isinstance(value, str) or value not in ENGINE_IDS:
        raise MotionError(
            "MOTION_ENGINE_INVALID",
            f"Unknown motion engine: {value!r}",
            field="motion.engine",
            remediation="Choose hyperframes, remotion, or code-drawn.",
        )
    return value


def _contract(value: Any, name: str, code: str) -> None:
    try:
        validate_document(value, name)
    except ContractError as error:
        raise MotionError(code, str(error)) from error


def validate_motion_config(value: Any) -> dict[str, Any]:
    _contract(value, "avo.motion.schema.json#/$defs/config", "MOTION_CONFIG_INVALID")
    return deepcopy(value)


def _seal(value: dict[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Expected a JSON object.")
    result = deepcopy(value)
    try:
        result[field] = document_hash_excluding(result, field)
    except ContractError as error:
        raise MotionError("CODE_DRAWN_INPUT_INVALID", str(error)) from error
    return result


def seal_composition(value: dict[str, Any]) -> dict[str, Any]:
    return _seal(value, "manifestHash")


def seal_input_lock(value: dict[str, Any]) -> dict[str, Any]:
    return _seal(value, "inputLockHash")


def _check_seal(value: dict[str, Any], field: str) -> None:
    if value[field] != document_hash_excluding(value, field):
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE", f"{field} does not match its content."
        )


def local_composition_path(root: Path, name: str) -> Path:
    """Resolve one normalized local input, including symlink containment."""
    posix = PurePosixPath(name)
    invalid = (
        not name
        or "\\" in name
        or ":" in name
        or posix.is_absolute()
        or ".." in posix.parts
        or posix.as_posix() != name
    )
    if invalid:
        raise MotionError("CODE_DRAWN_INPUT_INVALID", f"Unsafe local path: {name}")
    base = Path(root).resolve()
    target = (base / posix).resolve()
    try:
        target.relative_to(base)
    except ValueError as error:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", f"Input escaped composition root: {name}"
        ) from error
    return target


def _validate_render_contract(contract: dict[str, Any]) -> None:
    rate = contract["frameRate"]
    if any(type(rate[key]) is not int for key in ("num", "den")):
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Frame rate must use integers.")
    if math.gcd(rate["num"], rate["den"]) != 1:
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Frame rate must be reduced.")
    if contract["width"] * contract["height"] > MAX_CAPTURE_PIXELS:
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Capture exceeds pixel budget.")
    transparent = contract["background"]["mode"] == "transparent"
    expected = "straight" if transparent else "opaque"
    if contract["alphaMode"] != expected:
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Background and alpha disagree.")


def _verify_file(root: Path, item: dict[str, Any], verify: bool) -> None:
    target = local_composition_path(root, item["path"])
    if not verify:
        return
    if not target.is_file():
        raise MotionError("CODE_DRAWN_ASSET_NOT_READY", f"Missing input: {target}")
    observed = file_fingerprint(target)
    if any(observed[key] != item[key] for key in ("sha256", "sizeBytes")):
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE", f"Input fingerprint changed: {target}"
        )


def validate_composition(
    value: dict[str, Any], *, root: Path, verify_files: bool = True
) -> dict[str, Any]:
    _contract(value, "avo.code-drawn.schema.json", "CODE_DRAWN_INPUT_INVALID")
    _check_seal(value, "manifestHash")
    _validate_render_contract(value["renderContract"])
    entries = [*value["files"], *value["assets"], *value["dependencies"]]
    paths = [entry["path"] for entry in entries]
    if len(set(paths)) != len(paths):
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Duplicate declared input path.")
    if value["entry"] not in {entry["path"] for entry in value["files"]}:
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Entry is not a declared source.")
    for item in entries:
        _verify_file(root, item, verify_files)
    return deepcopy(value)


def load_composition(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", f"Cannot read composition {path}: {error}"
        ) from error
    return validate_composition(value, root=path.parent)


def validate_input_lock(value: dict[str, Any]) -> dict[str, Any]:
    _contract(
        value, "avo.code-drawn.schema.json#/$defs/inputLock", "CODE_DRAWN_INPUT_INVALID"
    )
    _check_seal(value, "inputLockHash")
    if value["inputsHash"] != content_hash(value["inputs"]):
        raise MotionError("CODE_DRAWN_LOCK_STALE", "Input set hash does not match.")
    if value["bindingMode"] == "canonical":
        bounds = value["range"]
        if bounds["endFrameExclusive"] <= bounds["startFrame"]:
            raise MotionError("CODE_DRAWN_INPUT_INVALID", "Canonical range is empty.")
    return deepcopy(value)


def resolve_motion_selection(
    *,
    global_settings: dict[str, Any] | None = None,
    provider_settings: dict[str, Any] | None = None,
    project_settings: dict[str, Any] | None = None,
    invocation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve explicit motion settings without mutating or hiding invalid scopes."""
    scopes = [
        ("global", global_settings),
        ("provider", provider_settings),
        ("project", project_settings),
        ("invocation", invocation),
    ]
    validated = [
        (source, validate_motion_config(value) if value is not None else None)
        for source, value in scopes
    ]
    resolved = resolve_scoped_settings(
        defaults={"engine": DEFAULT_ENGINE}, scopes=validated
    )
    source = resolved.sources["engine"]
    masked = [
        {"engine": value["engine"], "source": name}
        for name, value in validated
        if value and "engine" in value and name != source
    ]
    return {
        "engine": resolved.values["engine"],
        "source": source,
        "advanced": resolved.values["engine"] == "code-drawn",
        "resolutionHash": resolved.policy_hash,
        "maskedChoices": masked,
    }


def _read_motion_document(
    path: Path, *, missing: bool = False
) -> tuple[dict[str, Any], bytes | None]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        if missing:
            return {"schemaVersion": "1.0.0"}, None
        raise MotionError(
            "MOTION_TARGET_INVALID", f"Motion target does not exist: {path}"
        ) from error
    except OSError as error:
        raise MotionError(
            "MOTION_CONFIG_INVALID", f"Cannot read motion target {path}: {error}"
        ) from error
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise MotionError(
            "MOTION_CONFIG_INVALID", f"Invalid JSON at {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise MotionError("MOTION_CONFIG_INVALID", f"Expected an object at {path}.")
    return value, raw


def _motion_schema_check(document: dict[str, Any], scope: str, root: Path) -> None:
    if scope == "global":
        _contract(document, "avo.motion.schema.json", "MOTION_CONFIG_INVALID")
    elif scope == "project":
        _contract(document, "avo.project.schema.json", "MOTION_CONFIG_INVALID")
    else:
        schema = root / "providers" / "avo.provider.schema.json"
        if not schema.is_file():
            schema = (
                Path(__file__).resolve().parents[2]
                / "providers/avo.provider.schema.json"
            )
        try:
            validate_document(document, str(schema), root=schemas_dir())
        except ContractError as error:
            raise MotionError("MOTION_CONFIG_INVALID", str(error)) from error
    parent = document.get("routingOverrides", {}) if scope == "provider" else document
    if "motion" in parent:
        validate_motion_config(parent["motion"])


def _provider_motion_target(provider: str, root: Path) -> Path:
    if not isinstance(provider, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]*", provider
    ):
        raise MotionError(
            "MOTION_TARGET_INVALID", "Provider must be an exact valid slug."
        )
    base = (root / "providers").resolve()
    target = (base / provider / "avo.provider.json").resolve()
    if not target.is_relative_to(base):
        raise MotionError("MOTION_TARGET_INVALID", "Provider target escaped providers.")
    return target


def _project_motion_target(
    project: Path | str, provider: str | None, root: Path
) -> tuple[Path, dict[str, Any], bytes]:
    target = Path(project).expanduser().resolve()
    if target.is_dir():
        target /= "avo.project.json"
    document, raw = _read_motion_document(target)
    _motion_schema_check(document, "project", root)
    declared = Path(document["rawDir"]).expanduser()
    raw_dir = (
        (target.parent / declared).resolve()
        if not declared.is_absolute()
        else declared.resolve()
    )
    if raw_dir != target.parent or (provider and provider != document["provider"]):
        raise MotionError(
            "MOTION_TARGET_INVALID", f"Project provider/rawDir does not match {target}."
        )
    return target, document, raw


def _motion_documents(
    *, project: Path | str | None, provider: str | None, root: Path, home: Path
) -> dict[str, tuple[Path | None, dict[str, Any], bytes | None]]:
    global_path = (home / ".avo" / "preferences.json").resolve()
    global_doc, global_raw = _read_motion_document(global_path, missing=True)
    _motion_schema_check(global_doc, "global", root)
    result = {
        "global": (global_path, global_doc, global_raw),
        "provider": (None, {}, None),
        "project": (None, {}, None),
    }
    inferred_provider = project is not None and provider is None
    if project is not None:
        result["project"] = _project_motion_target(project, provider, root)
        provider = result["project"][1]["provider"]
    if provider:
        target = _provider_motion_target(provider, root)
        if inferred_provider and not target.exists():
            result["provider"] = (target, {}, None)
            return result
        document, raw = _read_motion_document(target)
        _motion_schema_check(document, "provider", root)
        if document["name"] != provider:
            raise MotionError(
                "MOTION_TARGET_INVALID", f"Provider identity does not match {target}."
            )
        result["provider"] = (target, document, raw)
    return result


def _document_motion(scope: str, document: dict[str, Any]) -> dict[str, Any] | None:
    parent = document.get("routingOverrides", {}) if scope == "provider" else document
    return parent.get("motion")


def _project_motion_settings(
    path: Path | None, document: dict[str, Any], root: Path
) -> dict[str, Any] | None:
    if path is None:
        return None
    from avo import video_registry

    registry = video_registry.find_video_by_raw_dir(
        path.parent, provider=document["provider"], root=root
    )
    settings: dict[str, Any] = {}
    for owner in ((registry or {}).get("defaults", {}), document):
        if "motion" in owner:
            settings.update(validate_motion_config(owner["motion"]))
    return settings


def _unavailable_motion(message: str, state: str) -> dict[str, Any]:
    return {
        "ready": False,
        "state": state,
        "checks": [],
        "blockers": [message],
        "nextActions": [
            "Install/support the selected engine, or explicitly choose an available engine."
        ],
    }


def _hyperframes_readiness(root: Path, operation: str) -> dict[str, Any]:
    if operation not in {"check", "snapshot", "preview", "render"}:
        return _unavailable_motion(
            f"HyperFrames does not support operation {operation}.", "unsupported"
        )
    local = root / "node_modules" / ".bin"
    checks = [
        {"tool": "node", "ready": shutil.which("node") is not None},
        {"tool": "ffmpeg", "ready": shutil.which("ffmpeg") is not None},
        {
            "tool": "hyperframes",
            "ready": shutil.which("hyperframes") is not None
            or any(
                (local / name).is_file() for name in ("hyperframes", "hyperframes.cmd")
            ),
        },
    ]
    missing = [item["tool"] for item in checks if not item["ready"]]
    return {
        "ready": not missing,
        "state": "unavailable" if missing else "available",
        "checks": checks,
        "blockers": [f"Missing selected dependency: {name}" for name in missing],
        "nextActions": [f"Install or repair {name}." for name in missing],
    }


def _motion_readiness(engine: str, root: Path, operation: str) -> dict[str, Any]:
    if engine == "hyperframes":
        return _hyperframes_readiness(root, operation)
    if engine == "remotion":
        return _unavailable_motion(
            "Remotion has no working AVO adapter.", "unsupported"
        )
    if operation not in {"check", "snapshot", "render"}:
        return _unavailable_motion(
            f"Code-drawn does not support operation {operation}.", "unsupported"
        )
    from avo.motion_runtime import runtime_readiness

    return runtime_readiness()


def _recorded_motion(project: Path | None) -> tuple[dict | None, dict | None]:
    if project is None:
        return None, None
    from avo.timeline.lifecycle import PipelineRunStore
    from avo.timeline.workspace import TimelineWorkspace

    workspace = TimelineWorkspace.from_project(project)
    run = None
    if workspace.pipeline_run_path.is_file():
        document = PipelineRunStore(workspace.pipeline_run_path).load()
        run = (document.get("executionChoices") or {}).get("motion")
    recorded = None
    store = workspace.store("animation")
    if store.path.is_file():
        index = store.load_index()
        head = index.get("headRevisionId")
        if head:
            revision = store.revision(head)
            strategy = revision["snapshot"]
            framework = strategy["framework"]
            recorded = {
                "revisionId": head,
                "sha256": revision["contentHash"],
                "framework": framework,
                "components": [
                    {
                        "instanceId": (
                            item.get("extensions", {})
                            .get("codeDrawn", {})
                            .get("instanceId")
                            or item["componentId"]
                        ),
                        "engine": framework,
                    }
                    for item in strategy["components"]
                ],
            }
    return deepcopy(run), recorded


def _motion_inspection(
    documents: dict[str, tuple[Path | None, dict[str, Any], bytes | None]],
    root: Path,
    *,
    invocation: str | dict[str, Any] | None = None,
    operation: str = "render",
) -> dict[str, Any]:
    scoped = {
        name: _document_motion(name, document)
        for name, (_, document, _) in documents.items()
    }
    if isinstance(invocation, str):
        invocation = {"engine": validate_engine(invocation)}
    project_path, project_doc, _ = documents["project"]
    selection = resolve_motion_selection(
        global_settings=scoped["global"],
        provider_settings=scoped["provider"],
        project_settings=_project_motion_settings(project_path, project_doc, root),
        invocation=invocation,
    )
    try:
        run, recorded = _recorded_motion(project_path)
    except (OSError, ValueError, KeyError) as error:
        raise MotionError(
            "MOTION_CONFIG_INVALID",
            f"Cannot inspect recorded motion for {project_path}: {error}",
        ) from error
    return {
        "operation": "engine-show",
        "status": "ok",
        "selection": selection,
        "savedPreferences": {
            name: {
                "engine": (scoped[name] or {}).get("engine"),
                "target": str(path) if path else None,
            }
            for name, (path, _, _) in documents.items()
        },
        "runSelection": run,
        "recordedAnimation": recorded,
        "readiness": _motion_readiness(selection["engine"], root, operation),
        "artifacts": [],
        "checks": [],
        "errors": [],
    }


def inspect_motion(
    *,
    project: Path | str | None = None,
    provider: str | None = None,
    invocation: str | dict[str, Any] | None = None,
    root: Path | None = None,
    home: Path | None = None,
    operation: str = "render",
) -> dict[str, Any]:
    """Inspect new-authoring preferences separately from recorded run/artifact choices."""
    root = repo_root(root)
    home = Path(home) if home is not None else Path.home()
    documents = _motion_documents(
        project=project, provider=provider, root=root, home=home
    )
    return _motion_inspection(
        documents, root, invocation=invocation, operation=operation
    )


def _validate_motion_write_target(
    scope: str, project: Path | str | None, provider: str | None
) -> None:
    if scope not in {"global", "provider", "project"}:
        raise MotionError(
            "MOTION_SCOPE_REQUIRED", "Choose global, provider, or project."
        )
    if scope != "global" and not {"provider": provider, "project": project}[scope]:
        raise MotionError(
            "MOTION_SCOPE_REQUIRED", f"An exact {scope} target is required."
        )


def _motion_candidate(
    original: dict[str, Any], scope: str, engine: str | None
) -> tuple[dict[str, Any], bool]:
    candidate = deepcopy(original)
    parent = (
        candidate.setdefault("routingOverrides", {})
        if scope == "provider"
        else candidate
    )
    changed = engine is not None or "engine" in parent.get("motion", {})
    if changed:
        settings = parent.setdefault("motion", {})
        if engine is None:
            settings.pop("engine", None)
        else:
            settings["engine"] = validate_engine(engine)
    return candidate, changed


def _save_motion_candidate(
    target: Path,
    original_bytes: bytes | None,
    candidate: dict[str, Any],
    scope: str,
    root: Path,
) -> None:
    _motion_schema_check(candidate, scope, root)
    try:
        observed = target.read_bytes() if target.exists() else None
        if observed != original_bytes:
            raise MotionError(
                "MOTION_CONFIG_CHANGED", f"Motion target changed concurrently: {target}"
            )
        atomic_write_json(target, candidate)
    except OSError as error:
        raise MotionError(
            "MOTION_WRITE_FAILED", f"Cannot save motion target {target}: {error}"
        ) from error


def _replace_motion_preference(
    *,
    scope: str,
    engine: str | None,
    project: Path | str | None,
    provider: str | None,
    root: Path | None,
    home: Path | None,
) -> dict[str, Any]:
    _validate_motion_write_target(scope, project, provider)
    root = repo_root(root)
    home = Path(home) if home is not None else Path.home()
    documents = _motion_documents(
        project=project, provider=provider, root=root, home=home
    )
    target, original, original_bytes = documents[scope]
    candidate, changed = _motion_candidate(original, scope, engine)
    proposed = {**documents, scope: (target, candidate, original_bytes)}
    result = _motion_inspection(proposed, root)
    if changed:
        _save_motion_candidate(target, original_bytes, candidate, scope, root)
    result["operation"] = "engine-reset" if engine is None else "engine-set"
    return result


def set_motion_preference(
    *,
    scope: str,
    engine: str,
    project: Path | str | None = None,
    provider: str | None = None,
    root: Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    validate_engine(engine)
    return _replace_motion_preference(
        scope=scope,
        engine=engine,
        project=project,
        provider=provider,
        root=root,
        home=home,
    )


def reset_motion_preference(
    *,
    scope: str,
    project: Path | str | None = None,
    provider: str | None = None,
    root: Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    return _replace_motion_preference(
        scope=scope,
        engine=None,
        project=project,
        provider=provider,
        root=root,
        home=home,
    )


