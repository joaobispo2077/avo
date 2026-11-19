"""Read current local speech dependencies without loading a speech runtime."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from avo.model_sources import PreflightError, resolve_job
from avo.timeline.ports import ToolError
from avo.transcribe import MODEL_FILES, source_fingerprint


def _speech_runtime_versions():
    observed = {}
    for name in ("faster-whisper", "ctranslate2", "av", "onnxruntime", "numpy"):
        try:
            observed[name] = version(name)
        except PackageNotFoundError:
            observed[name] = None
    return observed


def _dependency_files(paths):
    """Read current local bytes without provisioning or importing model runtimes."""
    files = {}
    for path in paths:
        path = Path(path)
        try:
            files[str(path.resolve())] = source_fingerprint(path)["sha256"]
        except OSError:
            files[str(path.resolve())] = None
    return {
        "status": "observed" if files and all(files.values()) else "unknown",
        "files": files,
    }


def _alignment_config_complete(runtime, punkt_files):
    models = runtime.get("models") or {}
    return bool(
        runtime.get("python")
        and punkt_files
        and models
        and all(model.get("path") and model.get("files") for model in models.values())
    )


def _alignment_dependencies(runtime):
    paths = []
    if runtime.get("python"):
        paths.append(Path(runtime["python"]))
    paths.extend(_configured_model_files(runtime.get("models") or {}))
    punkt = runtime.get("nltkData")
    punkt_files = (
        [path for path in Path(punkt).rglob("*") if path.is_file()] if punkt else []
    )
    paths.extend(punkt_files)
    result = {"configured": runtime, **_dependency_files(paths)}
    if not _alignment_config_complete(runtime, punkt_files):
        result["status"] = "unknown"
    return result


def _configured_model_files(models):
    paths = []
    for model in models.values():
        directory = Path(model.get("path") or ".")
        paths.extend(directory / name for name in (model.get("files") or {}))
    return paths


def transcription_runtime(effective):
    runtime = (effective.get("runtimeRefs") or {}).get("transcription") or {}
    device = runtime.get("device", "cpu")
    if device not in {"cpu", "cuda"}:
        raise ValueError("cutting transcription device must be cpu or cuda")
    return {
        "device": device,
        "computeType": runtime.get("computeType", "int8"),
    }


def speech_dependency_bindings(
    project, effective, *, resolver=resolve_job, runtime_reader=None
):
    runtime = (effective.get("runtimeRefs") or {}).get("alignment") or {}
    try:
        resolved = resolver("transcribe", project=project)
        source = resolved.pin.get("source") or {}
        if not source.get("artifactPath"):
            raise ValueError("prepared local ASR artifact is unavailable")
        directory = Path(source["artifactPath"])
        transcription = {
            "model": resolved.id,
            "policyHash": resolved.policy_hash,
            "runtime": runtime_reader()
            if runtime_reader
            else transcription_runtime(effective),
            "versions": _speech_runtime_versions(),
            **_dependency_files(directory / name for name in MODEL_FILES),
        }
    except (PreflightError, ToolError, OSError, RuntimeError, ValueError) as exc:
        transcription = {"status": "unknown", "reason": str(exc)}
    return {
        "transcription": transcription,
        "alignment": _alignment_dependencies(runtime),
    }
