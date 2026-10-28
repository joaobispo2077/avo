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


def _drawing_frame_rate(value: str) -> dict[str, int]:
    if not isinstance(value, str) or not re.fullmatch(
        r"[1-9][0-9]*/[1-9][0-9]*", value
    ):
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Frame rate must be num/den.")
    numerator, denominator = map(int, value.split("/"))
    divisor = math.gcd(numerator, denominator)
    return {"num": numerator // divisor, "den": denominator // divisor}


def _drawing_contract(
    width: int,
    height: int,
    fps: str,
    frames: int,
    background: str,
    background_color: str | None,
) -> dict[str, Any]:
    if background not in {"opaque", "transparent"}:
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Choose opaque or transparent.")
    if background == "opaque":
        if not isinstance(background_color, str) or not re.fullmatch(
            r"#[0-9a-fA-F]{6}", background_color
        ):
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID",
                "Opaque drawing needs an explicit #rrggbb color.",
            )
        fill = {"mode": "opaque", "color": background_color}
    else:
        if background_color is not None:
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID",
                "Transparent drawing cannot include an opaque color.",
            )
        fill = {"mode": "transparent"}
    contract = {
        "width": width,
        "height": height,
        "frameRate": _drawing_frame_rate(fps),
        "frameCount": frames,
        "background": fill,
        "alphaMode": "straight" if background == "transparent" else "opaque",
        "captureColorSpace": "srgb",
        "compositeColorSpace": "sdr-bt709",
        "quality": {"spatialSamples": 1, "temporalSamples": 1},
    }
    _contract(
        contract,
        "avo.code-drawn.schema.json#/properties/renderContract",
        "CODE_DRAWN_INPUT_INVALID",
    )
    _validate_render_contract(contract)
    return contract


def _drawing_template_tree(resource: Any, prefix: str = "") -> dict[str, bytes]:
    if not resource.is_dir():
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", f"Drawing template is missing: {resource}"
        )
    result = {}
    for child in sorted(resource.iterdir(), key=lambda item: item.name):
        name = prefix + child.name
        if child.is_dir():
            result.update(_drawing_template_tree(child, name + "/"))
        else:
            result[name] = child.read_bytes()
    return result


def _drawing_substitutions(contract: dict[str, Any]) -> dict[str, str]:
    return {
        "__WIDTH__": str(contract["width"]),
        "__HEIGHT__": str(contract["height"]),
        "__BACKGROUND__": json.dumps(contract["background"].get("color")),
        "__SEED__": "7",
        "__FRAMES__": str(contract["frameCount"]),
        "__FPS_NUM__": str(contract["frameRate"]["num"]),
        "__FPS_DEN__": str(contract["frameRate"]["den"]),
    }


def _drawing_template_bytes(data: bytes, replacements: dict[str, str]) -> bytes:
    text = data.decode("utf-8")
    for token, value in replacements.items():
        text = text.replace(token, value)
    return text.encode("utf-8")


def _brush_scaffold_inputs(
    brush_resources: tuple[Path, Path] | None,
) -> dict[str, bytes]:
    from avo.templates.code_drawn import (
        BRUSH_LICENSE_SHA256,
        BRUSH_SHA256,
        brush_cache_paths,
    )

    paths = brush_resources if brush_resources is not None else brush_cache_paths()
    result = {}
    for path, name, digest in zip(
        paths,
        ("assets/brush.js", "assets/brush-LICENSE.md"),
        (BRUSH_SHA256, BRUSH_LICENSE_SHA256),
        strict=True,
    ):
        try:
            data = Path(path).read_bytes()
        except OSError as error:
            raise MotionError(
                "CODE_DRAWN_ASSET_NOT_READY",
                f"Missing brush input: {path}",
                remediation="Run animation runtime-install --engine code-drawn --brush.",
            ) from error
        if hashlib.sha256(data).hexdigest() != digest:
            raise MotionError(
                "CODE_DRAWN_ASSET_NOT_READY", f"Brush input changed: {path}"
            )
        result[name] = data
    return result


def _drawing_file(path: str, data: bytes, **fields: Any) -> dict[str, Any]:
    return {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "sizeBytes": len(data),
        **fields,
    }


def _drawing_manifest(
    route: str,
    contract: dict[str, Any],
    sources: dict[str, bytes],
    brush: dict[str, bytes],
) -> dict[str, Any]:
    from avo.templates.code_drawn import BRUSH_VERSION

    dependencies = []
    assets = []
    if brush:
        license_path = "assets/brush-LICENSE.md"
        dependencies.append(
            _drawing_file(
                "assets/brush.js",
                brush["assets/brush.js"],
                name="p5.brush",
                version=BRUSH_VERSION,
                build="standalone",
                licenseRef=license_path,
            )
        )
        assets.append(
            _drawing_file(
                license_path,
                brush[license_path],
                id="brush-license",
                kind="data",
                rightsRef=license_path,
            )
        )
    return seal_composition(
        {
            "schemaVersion": "1.0.0",
            "compositionId": f"code-drawn-{route}",
            "engine": "code-drawn",
            "drawingRoute": route,
            "entry": "index.html",
            "sourceRevision": "source-r0001",
            "files": [
                _drawing_file(path, data, role="source")
                for path, data in sorted(sources.items())
            ],
            "assets": assets,
            "dependencies": dependencies,
            "seed": 7,
            "renderContract": contract,
        }
    )


def _write_drawing_scaffold(
    destination: Path,
    files: dict[str, bytes],
    manifest: dict[str, Any],
) -> None:
    try:
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "assets").mkdir()
        for relative, data in files.items():
            target = local_composition_path(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
        with (destination / "composition.json").open(
            "x", encoding="utf-8", newline="\n"
        ) as stream:
            json.dump(manifest, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
    except OSError as error:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            f"Could not create scaffold {destination}: {error}. Existing or partial files were preserved.",
        ) from error


def scaffold_code_drawn(
    destination: Path,
    *,
    route: str,
    width: int,
    height: int,
    fps: str,
    frames: int,
    background: str = "opaque",
    background_color: str | None = None,
    brush_resources: tuple[Path, Path] | None = None,
) -> dict[str, Any]:
    """Copy generic package resources into a new editable drawing workspace."""
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            f"Scaffold destination already exists: {destination}",
        )
    if route not in {"canvas", "svg", "brush"}:
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Choose canvas, svg, or brush.")
    contract = _drawing_contract(
        width, height, fps, frames, background, background_color
    )
    replacements = _drawing_substitutions(contract)
    package = resources.files("avo.templates.code_drawn")
    sources = {
        path: _drawing_template_bytes(data, replacements)
        for path, data in _drawing_template_tree(package.joinpath(route)).items()
    }
    documents = {
        path: _drawing_template_bytes(data, replacements)
        for path, data in _drawing_template_tree(
            package.joinpath("project-documents")
        ).items()
    }
    brush = _brush_scaffold_inputs(brush_resources) if route == "brush" else {}
    manifest = _drawing_manifest(route, contract, sources, brush)
    validate_composition(manifest, root=destination, verify_files=False)
    _write_drawing_scaffold(destination, {**sources, **documents, **brush}, manifest)
    return {
        "operation": "code-drawn-scaffold",
        "status": "ok",
        "selection": resolve_motion_selection(invocation={"engine": "code-drawn"}),
        "savedPreferences": {},
        "runSelection": None,
        "recordedAnimation": None,
        "readiness": {
            "ready": True,
            "state": "available",
            "checks": [{"name": "local-starter", "ready": True}],
            "blockers": [],
            "nextActions": [],
        },
        "artifacts": [
            {
                "path": str(destination / "composition.json"),
                "sha256": file_fingerprint(destination / "composition.json")["sha256"],
            }
        ],
        "checks": [],
        "errors": [],
    }


def _observed_drawing_environment(environment: dict[str, Any] | None) -> dict[str, Any]:
    required = {
        "platform",
        "dependencies",
        "browserVersion",
        "browserRevision",
        "graphics",
        "driverSha256",
        "encoderSha256",
        "locale",
        "timezone",
        "colorSpace",
    }
    if not isinstance(environment, dict) or required - environment.keys():
        raise MotionError(
            "CODE_DRAWN_RUNTIME_MISSING",
            "A complete observed drawing runtime environment is required.",
            remediation="Run a selected-engine check to observe the managed browser and encoder.",
        )
    _contract(
        environment,
        "avo.code-drawn.schema.json#/$defs/inputLock/properties/environment",
        "CODE_DRAWN_INPUT_INVALID",
    )
    return deepcopy(environment)


def _drawing_generator_identity() -> dict[str, str]:
    executable = file_fingerprint(Path(sys.executable).resolve())["sha256"]
    if getattr(sys, "frozen", False):
        # Frozen program modules are embedded in the actual engine executable.
        source_hash = executable
    else:
        package = Path(__file__).resolve().parent
        files = (
            "motion.py",
            "motion_runtime.py",
            "adapters/motion/code_drawn.py",
            "timeline/contracts.py",
            "templates/code_drawn/__init__.py",
        )
        source_hash = content_hash(
            {name: file_fingerprint(package / name)["sha256"] for name in files}
        )
    return {
        "adapterId": "code-drawn",
        "version": "1.0.0",
        "executableSha256": executable,
        "sourceSha256": source_hash,
    }


def _drawing_input(
    target: Path, artifact_id: str, role: str, declared: dict[str, Any] | None = None
) -> dict[str, Any]:
    try:
        fingerprint = file_fingerprint(target)
    except OSError as error:
        raise MotionError(
            "CODE_DRAWN_ASSET_NOT_READY", f"Cannot read drawing input {target}: {error}"
        ) from error
    if declared and any(
        fingerprint[key] != declared[key] for key in ("sha256", "sizeBytes")
    ):
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE", f"Drawing input changed while freezing: {target}"
        )
    return {
        "artifactId": artifact_id,
        "fingerprint": fingerprint,
        "ancestryRole": role,
    }


def _drawing_asset_ancestry(item: dict[str, Any]) -> tuple[str, str]:
    reference = item.get("sourceRef")
    if reference is None:
        return "drawing-assets:" + item["path"], "dependency"
    _contract(
        reference,
        "avo.code-drawn.schema.json#/properties/assets/items/properties/sourceRef",
        "CODE_DRAWN_INPUT_INVALID",
    )
    if "sourceId" in reference:
        return reference["sourceId"], "source"
    return reference["assetId"], "generated"


def _frozen_drawing_inputs(
    composition: Path, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    inputs = [_drawing_input(composition, "drawing-manifest", "dependency")]
    for section in ("files", "assets", "dependencies"):
        for item in sorted(manifest[section], key=lambda entry: entry["path"]):
            artifact_id, role = (
                _drawing_asset_ancestry(item)
                if section == "assets"
                else (f"drawing-{section}:{item['path']}", "dependency")
            )
            target = local_composition_path(composition.parent, item["path"])
            inputs.append(_drawing_input(target, artifact_id, role, item))
    return inputs


def _drawing_reference_identity(
    reference: dict, include_engine: bool
) -> tuple[str, dict]:
    expected = {"instanceId", "manifestRef"} | ({"engine"} if include_engine else set())
    if not isinstance(reference, dict) or set(reference) != expected:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", "Incomplete code-drawn manifest reference."
        )
    instance = reference["instanceId"]
    if not isinstance(instance, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{2,63}", instance
    ):
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Invalid code-drawn instanceId.")
    if include_engine and reference["engine"] != "code-drawn":
        raise MotionError("CODE_DRAWN_INPUT_INVALID", "Incompatible generated engine.")
    ref = reference["manifestRef"]
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", "Invalid manifest fingerprint reference."
        )
    return instance, ref


def validate_code_drawn_reference(
    reference: dict[str, Any], *, root: Path, include_engine: bool = False
) -> dict[str, Any]:
    """Validate a logical local source without granting render or approval authority."""
    instance, ref = _drawing_reference_identity(reference, include_engine)
    target = local_composition_path(root, str(ref["path"]))
    required = Path(root).resolve() / "edit" / "derived" / "components" / instance
    if (
        not target.is_relative_to(required.resolve())
        or target.name != "composition.json"
    ):
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            f"Manifest path does not belong to instance {instance}: {target}",
        )
    if not target.is_file() or file_fingerprint(target)["sha256"] != ref["sha256"]:
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE",
            f"Manifest fingerprint changed or missing: {target}",
        )
    return load_composition(target)


def _require_drawing_basis(snapshots: dict, lock: dict) -> None:
    if (snapshots["bmap"].get("basis") or {}).get("sha256") != lock["cmap"]:
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE", "BMap requires the current approved CMap."
        )
    if (snapshots["tracks"].get("basis") or {}).get("sha256") != lock["bmap"]:
        raise MotionError("CODE_DRAWN_LOCK_STALE", "Tracks requires the current BMap.")
    dependencies = snapshots["animation"].get("dependencies") or {}
    if any(dependencies.get(name) != lock[name] for name in ("cmap", "bmap", "tracks")):
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE",
            "Animation requires current canonical strategy/Tracks dependencies.",
        )


def _require_current_drawing_cut(workspace: Any, snapshots: dict) -> None:
    approval = workspace.store("cmap").effective_approval()
    cut_output = (snapshots["bmap"].get("basis") or {}).get("outputSha256")
    if not approval or approval["candidateSha256"] != cut_output:
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE",
            "Drawing BMap basis differs from the current approved cut output.",
        )


def _canonical_drawing_heads(workspace: Any) -> tuple[dict, dict]:
    snapshots, lock = {}, {}
    for name in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        index = workspace.require_active(name)
        revision = workspace.store(name).revision(index["headRevisionId"])
        lock[name] = revision["contentHash"]
        snapshots[name] = revision["snapshot"]
    for name in ("cmap", "sync-map"):
        approval = workspace.store(name).effective_approval()
        if not approval or approval["subject"]["contentSha256"] != lock[name]:
            raise MotionError(
                "CODE_DRAWN_LOCK_STALE",
                f"Current approved {name} is required for canonical drawing generation.",
            )
    _require_drawing_basis(snapshots, lock)
    _require_current_drawing_cut(workspace, snapshots)
    return snapshots, lock


def _drawing_logical_binding(snapshots: dict, instance_id: str) -> tuple[dict, dict]:
    strategy = snapshots["animation"]
    if strategy.get("framework") != "code-drawn":
        raise MotionError(
            "MOTION_ENGINE_UNSUPPORTED", "Recorded animation engine is not code-drawn."
        )
    references = [
        component.get("extensions", {}).get("codeDrawn")
        for component in strategy.get("components", [])
    ]
    matches = [
        ref for ref in references if ref and ref.get("instanceId") == instance_id
    ]
    layers = [
        layer
        for layer in snapshots["tracks"].get("videoTracks", {}).get("layers", [])
        if layer.get("generatedSourceRef", {}).get("instanceId") == instance_id
    ]
    if len(matches) != 1 or len(layers) != 1:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            f"Exactly one strategy and Tracks binding required for {instance_id}.",
        )
    return matches[0], layers[0]


def _drawing_region(layer: dict, contract: dict) -> dict:
    from fractions import Fraction

    regions = layer.get("regions") or []
    if len(regions) != 1:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            "One contiguous canonical region is required per drawing instance.",
        )
    rate = Fraction(contract["frameRate"]["num"], contract["frameRate"]["den"])
    region = regions[0]
    base = region.get("timebase") or {"num": 1, "den": 1000}
    frames = [
        Fraction(region[key] * base["num"], base["den"]) * rate
        for key in ("startTicks", "endTicks")
    ]
    if (
        any(frame.denominator != 1 for frame in frames)
        or frames[1] - frames[0] != contract["frameCount"]
    ):
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            "Drawing rate/count does not exactly cover its canonical region.",
        )
    return {"startFrame": int(frames[0]), "endFrameExclusive": int(frames[1])}


def _drawing_placement(layer: dict, contract: dict) -> dict:
    role = layer.get("role")
    if role not in {"base", "overlay", "caption", "graphic"}:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", f"Unsupported drawing layer role: {role}"
        )
    if role == "base" and contract["alphaMode"] != "opaque":
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", "A generated base must be opaque."
        )
    return {
        "x": 0,
        "y": 0,
        "width": contract["width"],
        "height": contract["height"],
        **(layer.get("placement") or {}),
        "zOrder": layer.get("zOrder", layer.get("order", 0)),
        "layerRole": role,
    }


def _require_drawing_asset_parent(
    item: dict, originals: dict, generated_service: Any
) -> None:
    artifact_id, role = _drawing_asset_ancestry(item)
    if role == "dependency":
        return
    if role == "source":
        source = originals.get(artifact_id)
        if source is None:
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID",
                f"Unknown original source {artifact_id} for drawing asset {item['path']}.",
            )
        expected = source["fingerprint"]
    else:
        parent = generated_service.load(artifact_id)
        if parent["recordHash"] != item["sourceRef"]["recordHash"]:
            raise MotionError(
                "CODE_DRAWN_LOCK_STALE",
                f"Generated parent record changed for drawing asset {item['path']}: {artifact_id}.",
            )
        expected = parent["output"]
    if any(item[field] != expected.get(field) for field in ("sha256", "sizeBytes")):
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE",
            f"Drawing asset {item['path']} fingerprint differs from its {role} parent {artifact_id}.",
        )


def _require_drawing_asset_parents(workspace: Any, manifest: dict, cmap: dict) -> None:
    from avo.timeline.generated_assets import GeneratedAssetService

    originals = {source["sourceId"]: source for source in cmap["sources"]}
    service = GeneratedAssetService(workspace)
    for item in manifest["assets"]:
        _require_drawing_asset_parent(item, originals, service)


def canonical_code_drawn_binding(workspace: Any, instance_id: str) -> dict[str, Any]:
    """Derive one source, output range and placement from current canonical stores."""
    snapshots, lock = _canonical_drawing_heads(workspace)
    reference, layer = _drawing_logical_binding(snapshots, instance_id)
    manifest = validate_code_drawn_reference(reference, root=workspace.raw_dir)
    _require_drawing_asset_parents(workspace, manifest, snapshots["cmap"])
    if layer["generatedSourceRef"] != {"engine": "code-drawn", **reference}:
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE",
            f"Strategy/Tracks manifest identity differs for {instance_id}.",
        )
    contract = manifest["renderContract"]
    return {
        "reference": deepcopy(reference),
        "manifest": manifest,
        "canonicalInputLock": lock,
        "range": _drawing_region(layer, contract),
        "placement": _drawing_placement(layer, contract),
    }


def _drawing_manifest_stable(composition: Path, manifest: dict) -> None:
    try:
        current = json.loads(composition.read_bytes())
    except (OSError, ValueError) as error:
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE",
            f"Cannot revalidate manifest while freezing {composition}: {error}",
        ) from error
    if current != manifest:
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE", f"Manifest changed while freezing: {composition}"
        )


def _drawing_canonical_lock_fields(workspace, instance_id, composition):
    if workspace is None:
        return {}
    binding = canonical_code_drawn_binding(workspace, str(instance_id))
    if (
        Path(workspace.raw_dir) / binding["reference"]["manifestRef"]["path"]
    ).resolve() != composition:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            "Composition differs from the canonical manifest reference.",
        )
    return {key: binding[key] for key in ("canonicalInputLock", "range", "placement")}


def freeze_code_drawn_lock(
    composition: Path,
    *,
    environment: dict[str, Any] | None = None,
    canonical_binding: dict[str, Any] | None = None,
    workspace: Any = None,
    instance_id: str | None = None,
) -> dict[str, Any]:
    """Freeze standalone inputs using supplied observations, never invented approval."""
    observed = _observed_drawing_environment(environment)
    if canonical_binding is not None:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            "Canonical binding requires verification by the shared timeline coordinator.",
        )
    composition = Path(composition).expanduser().resolve()
    manifest = load_composition(composition)
    inputs = _frozen_drawing_inputs(composition, manifest)
    _drawing_manifest_stable(composition, manifest)
    binding = _drawing_canonical_lock_fields(workspace, instance_id, composition)
    lock = seal_input_lock(
        {
            "schemaVersion": "1.0.0",
            "bindingMode": "canonical" if binding else "standalone",
            "instanceId": instance_id if binding else manifest["compositionId"],
            **binding,
            "manifestRef": {
                "path": str(composition),
                "sha256": inputs[0]["fingerprint"]["sha256"],
            },
            "renderContractHash": content_hash(manifest["renderContract"]),
            "inputsHash": content_hash(inputs),
            "inputs": inputs,
            "generator": _drawing_generator_identity(),
            "environment": observed,
        }
    )
    return validate_input_lock(lock)


def verify_code_drawn_lock(
    composition: Path,
    lock: dict[str, Any],
    *,
    environment: dict[str, Any] | None = None,
    workspace: Any = None,
    instance_id: str | None = None,
) -> dict[str, Any]:
    """Compare original source identities; runtime freshness needs new observations."""
    original = validate_input_lock(lock)
    if original["bindingMode"] == "canonical" and workspace is None:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            "Canonical lock verification requires the shared timeline coordinator.",
        )
    current = freeze_code_drawn_lock(
        composition,
        environment=environment if environment is not None else original["environment"],
        workspace=workspace if original["bindingMode"] == "canonical" else None,
        instance_id=instance_id or original["instanceId"],
    )
    if current != original:
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE",
            f"Drawing inputs, generator or environment changed: {Path(composition)}",
            remediation="Freeze a new input lock and regenerate affected evidence.",
        )
    return original


def materialize_code_drawn(
    workspace: Any, instance_id: str, *, output: Path, adapter: Any
) -> dict[str, Any]:
    """Generate and admit an authority-bound asset through an injected renderer."""
    from avo.timeline.generated_assets import GeneratedAssetService
    from avo.timeline.store import write_immutable_json

    binding = canonical_code_drawn_binding(workspace, instance_id)
    composition = local_composition_path(
        workspace.raw_dir, binding["reference"]["manifestRef"]["path"]
    )
    service = GeneratedAssetService(workspace)
    service.validate_code_drawn_inputs(
        _frozen_drawing_inputs(composition, binding["manifest"])
    )
    output = Path(output).expanduser().resolve()
    if not output.is_relative_to(
        Path(workspace.raw_dir).resolve() / "edit" / "derived"
    ):
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            "Canonical generated output must remain under edit/derived.",
        )
    lock_path = output.with_suffix(".input-lock.json")
    if (
        output.exists()
        or lock_path.exists()
        or output.with_suffix(".generated-asset.json").exists()
    ):
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", f"Choose a new immutable output: {output}"
        )
    check = adapter.check(composition)
    environment = check["checks"][0]["evidence"]["environment"]
    lock = freeze_code_drawn_lock(
        composition,
        workspace=workspace,
        instance_id=instance_id,
        environment=environment,
    )
    write_immutable_json(lock_path, lock)
    result = adapter.render(
        composition, input_lock=lock_path, output=output, workspace=workspace
    )
    verify_code_drawn_lock(
        composition,
        lock,
        workspace=workspace,
        instance_id=instance_id,
        environment=environment,
    )
    record = json.loads(
        output.with_suffix(".generated-asset.json").read_text(encoding="utf-8")
    )
    service.register(record, code_drawn_environment=environment)
    service.admit(record["assetId"], code_drawn_environment=environment)
    return result


def _review_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", f"Cannot read review input {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", f"Review input must be an object: {path}"
        )
    return value


def _review_file_ref(path: Path) -> dict[str, str]:
    target = Path(path).resolve()
    return {"path": str(target), "sha256": file_fingerprint(target)["sha256"]}


def _review_source_identity(
    receipt: dict, lock: dict, manifest: dict, composition: Path, lock_path: Path
) -> None:
    extension = receipt["parameters"]["codeDrawn"]
    expected = {
        "instanceId": lock["instanceId"],
        "manifestRef": _review_file_ref(composition),
        "sourceRevision": manifest["sourceRevision"],
        "drawingRoute": manifest["drawingRoute"],
        "inputLockRef": _review_file_ref(lock_path),
        "inputLockHash": lock["inputLockHash"],
        "renderContractHash": content_hash(manifest["renderContract"]),
        "inputsHash": lock["inputsHash"],
    }
    if any(extension.get(key) != value for key, value in expected.items()):
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE", "Review source/receipt/lock identity changed."
        )
    pairs = [
        (lock["manifestRef"], expected["manifestRef"]),
        (lock["renderContractHash"], expected["renderContractHash"]),
        (receipt["generator"], lock["generator"]),
        (extension["captureEvidence"].get("environment"), lock["environment"]),
        (receipt["environment"]["platform"], lock["environment"]["platform"]),
        (receipt["environment"]["dependencies"], lock["environment"]["dependencies"]),
        (lock["inputs"], _frozen_drawing_inputs(composition, manifest)),
    ]
    if any(left != right for left, right in pairs):
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE",
            "Review source closure or recorded runtime changed.",
        )
    canonical = lock["bindingMode"] == "canonical"
    if ("canonicalInputLock" in extension) != canonical or extension.get(
        "canonicalInputLock"
    ) != lock.get("canonicalInputLock"):
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE", "Review changes the original binding mode."
        )


def _code_drawn_review_sources(
    source_receipts: list[Path], dependencies: dict[str, str]
) -> list[dict[str, Any]]:
    if not source_receipts:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", "Review requires actual source receipts."
        )
    result, seen = [], set()
    for value in source_receipts:
        path = Path(value).resolve()
        receipt = _review_json(path)
        _contract(
            receipt, "avo.generated-asset.schema.json", "CODE_DRAWN_INPUT_INVALID"
        )
        _check_seal(receipt, "recordHash")
        if (
            receipt["generator"]["adapterId"] != "code-drawn"
            or receipt["assetId"] in seen
        ):
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID",
                "Review requires unique code-drawn source assets.",
            )
        seen.add(receipt["assetId"])
        extension = receipt["parameters"]["codeDrawn"]
        composition = Path(extension["manifestRef"]["path"]).resolve()
        lock_path = Path(extension["inputLockRef"]["path"]).resolve()
        manifest = load_composition(composition)
        lock = validate_input_lock(_review_json(lock_path))
        _review_source_identity(receipt, lock, manifest, composition, lock_path)
        required = {
            "generated:" + receipt["assetId"]: receipt["recordHash"],
            "input-lock:" + lock["instanceId"]: lock["inputLockHash"],
        }
        if any(dependencies.get(key) != expected for key, expected in required.items()):
            raise MotionError(
                "CODE_DRAWN_LOCK_STALE",
                "Review dependency lock omits a source asset/input lock.",
            )
        result.append(
            {
                "engine": "code-drawn",
                "assetId": receipt["assetId"],
                "recordHash": receipt["recordHash"],
                "receiptRef": _review_file_ref(path),
                **{
                    key: deepcopy(extension[key])
                    for key in (
                        "instanceId",
                        "drawingRoute",
                        "sourceRevision",
                        "manifestRef",
                        "inputLockRef",
                        "inputLockHash",
                        "renderContractHash",
                        "inputsHash",
                        "outputVerification",
                    )
                },
                "generator": deepcopy(lock["generator"]),
                "environment": deepcopy(lock["environment"]),
                "dependencies": deepcopy(manifest["dependencies"]),
                "output": deepcopy(receipt["output"]),
            }
        )
    return result


def _positive_review_numbers(numbers: list[int]) -> None:
    if any(type(number) is not int or number <= 0 for number in numbers):
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            "Review target numbers must be positive integers.",
        )


def _review_candidate_contract(value: dict) -> dict:
    fields = {"width", "height", "frameRate", "frameCount"}
    if not isinstance(value, dict) or set(value) != fields:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", "Review requires the exact candidate contract."
        )
    _positive_review_numbers([value[key] for key in ("width", "height", "frameCount")])
    rate = value["frameRate"]
    if not isinstance(rate, dict) or set(rate) != {"num", "den"}:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", "Review frame rate must be a reduced rational."
        )
    _positive_review_numbers(list(rate.values()))
    if (
        math.gcd(rate["num"], rate["den"]) != 1
        or value["width"] * value["height"] > MAX_CAPTURE_PIXELS
    ):
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", "Unsupported review rate/pixel target."
        )
    return deepcopy(value)


def _review_transition_range(bounds: dict, count: int) -> None:
    if not isinstance(bounds, dict) or set(bounds) != {
        "startFrame",
        "endFrameExclusive",
    }:
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", "Review transition needs exact frame bounds."
        )
    if any(type(frame) is not int for frame in bounds.values()) or not (
        0 <= bounds["startFrame"] < bounds["endFrameExclusive"] <= count
    ):
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID", "Review transition range is invalid."
        )


def _review_sample_plan(
    count: int, samples: list[int] | None, ranges: list[dict] | None
) -> tuple[list[int], list[dict]]:
    frames = (
        list(samples)
        if samples is not None
        else [round(index * (count - 1) / 9) for index in range(10)]
    )
    if any(type(frame) is not int or not 0 <= frame < count for frame in frames):
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            "Review sample is outside the integer frame range.",
        )
    transitions = deepcopy(ranges or [])
    for bounds in transitions:
        _review_transition_range(bounds, count)
    return sorted({0, count - 1, *frames}), transitions


def _produce_review_previews(producer: Any, request: dict) -> dict:
    try:
        result = producer(**request)
        if not isinstance(result, dict):
            raise ValueError("Preview producer must return an object.")
        return result
    except Exception as error:
        raise MotionError(
            "CODE_DRAWN_RENDER_FAILED", f"Candidate preview generation failed: {error}"
        ) from error


def _review_artifacts(values: list[dict], output_dir: Path) -> list[dict]:
    result = []
    for item in values:
        path = Path(item["path"]).resolve()
        if not path.is_relative_to(output_dir) or not path.is_file():
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID",
                f"Review artifact is missing/outside its new directory: {path}",
            )
        fingerprint = file_fingerprint(path)
        result.append(
            {
                **deepcopy(item),
                "path": str(path),
                "sha256": fingerprint["sha256"],
                "sizeBytes": fingerprint["sizeBytes"],
            }
        )
    return result


def prepare_code_drawn_review(
    candidate: Path,
    *,
    dependencies: dict[str, str],
    render_profile: str,
    candidate_contract: dict,
    source_receipts: list[Path],
    output_dir: Path,
    producer: Any,
    sample_frames: list[int] | None = None,
    transition_ranges: list[dict] | None = None,
    loop_requested: bool = False,
) -> dict[str, Any]:
    """Prepare exact decoded-candidate review artifacts, never creator approval."""
    from avo.timeline.contracts import dependency_lock_hash
    from avo.timeline.review import (
        GateError,
        _validate_code_drawn_package,
        candidate_identity,
    )
    from avo.timeline.store import now_iso, write_immutable_json

    candidate, output_dir = Path(candidate).resolve(), Path(output_dir).resolve()
    if (
        output_dir.exists()
        or not candidate.is_file()
        or type(loop_requested) is not bool
    ):
        raise MotionError(
            "CODE_DRAWN_INPUT_INVALID",
            "Review needs a candidate, fresh output directory and boolean loop request.",
        )
    contract = _review_candidate_contract(candidate_contract)
    frames, transitions = _review_sample_plan(
        contract["frameCount"], sample_frames, transition_ranges
    )
    frozen_dependencies = deepcopy(dependencies)
    sources = _code_drawn_review_sources(source_receipts, frozen_dependencies)
    identity = candidate_identity(candidate, frozen_dependencies, render_profile)
    produced = _produce_review_previews(
        producer,
        {
            "candidate": candidate,
            "output_dir": output_dir,
            "candidate_contract": deepcopy(contract),
            "sample_frames": list(frames),
            "transition_ranges": deepcopy(transitions),
            "loop_requested": loop_requested,
        },
    )
    if (
        candidate_identity(candidate, dependencies, render_profile) != identity
        or dependencies != frozen_dependencies
    ):
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE",
            "Candidate/dependencies changed during review preparation.",
        )
    if _code_drawn_review_sources(source_receipts, frozen_dependencies) != sources:
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE", "Source inputs changed during review preparation."
        )
    package = {
        "schemaVersion": "1.0.0",
        "kind": "code-drawn-review",
        "packagePath": str(output_dir / "code-drawn-review.json"),
        "candidate": identity,
        "dependencyLockSha256": dependency_lock_hash(frozen_dependencies),
        "candidateContract": contract,
        "sources": sources,
        "sampleFrames": frames,
        "transitionRanges": transitions,
        "loopRequested": loop_requested,
        "artifacts": _review_artifacts(produced.get("artifacts") or [], output_dir),
        "findings": deepcopy(produced.get("findings") or []),
        "state": "needs-human-judgment",
        "approval": None,
        "createdAt": now_iso(),
    }
    package["reviewHash"] = document_hash_excluding(package, "reviewHash")
    try:
        _validate_code_drawn_package(
            package,
            candidate=candidate,
            dependencies=frozen_dependencies,
            render_profile=render_profile,
        )
    except GateError as error:
        raise MotionError("CODE_DRAWN_INPUT_INVALID", str(error)) from error
    write_immutable_json(Path(package["packagePath"]), package)
    return package
