"""Read current local speech dependencies without loading a speech runtime."""

from copy import deepcopy
from importlib.metadata import PackageNotFoundError, distributions, version
from itertools import islice
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


def _alignment_sites(runtime):
    if not runtime.get("python"):
        return []
    parent = Path(runtime["python"]).parent
    prefix = parent.parent if parent.name.lower() in {"scripts", "bin"} else parent
    roots = [prefix / "Lib/site-packages"]
    libraries = list(islice((prefix / "lib").glob("python*"), 17))
    if len(libraries) > 16:
        raise ValueError("Alignment runtime has ambiguous package roots")
    roots.extend(
        root / directory
        for root in libraries
        for directory in ("site-packages", "dist-packages")
    )
    return [str(path) for path in roots if path.is_dir()]


def _distribution_version(name, sites):
    matches = list(islice(distributions(name=name, path=sites), 2))
    if len(matches) != 1:
        return None
    value = matches[0].version
    return value if isinstance(value, str) and 0 < len(value) <= 128 else None


def _alignment_runtime_versions(runtime):
    """Read isolated environment metadata without importing its packages or Python."""
    packages = ("whisperx", "torch", "torchaudio", "transformers", "numpy", "nltk")
    unknown = dict.fromkeys(packages)
    try:
        sites = _alignment_sites(runtime)
        if not sites:
            return unknown
        return {name: _distribution_version(name, sites) for name in packages}
    except (OSError, ValueError, UnicodeError):
        return unknown


def _alignment_dependencies(runtime):
    runtime = deepcopy(runtime)
    paths = []
    if runtime.get("python"):
        paths.append(Path(runtime["python"]))
    paths.extend(_configured_model_files(runtime.get("models") or {}))
    punkt = runtime.get("nltkData")
    punkt_files = (
        [path for path in Path(punkt).rglob("*") if path.is_file()] if punkt else []
    )
    paths.extend(punkt_files)
    versions = _alignment_runtime_versions(runtime)
    result = {"configured": runtime, "versions": versions, **_dependency_files(paths)}
    if not _alignment_config_complete(runtime, punkt_files) or not all(
        versions.values()
    ):
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


def workspace_speech_dependencies(workspace):
    """Resolve current saved speech settings; never instantiate a media adapter."""
    from avo.init_project import load_config, load_provider
    from avo.paths import repo_root
    from avo.timeline.cutting_policy import resolve_cutting_policy

    root = repo_root()
    provider = {}
    if workspace.project.get("provider"):
        try:
            provider = load_provider(workspace.project["provider"], root=root)
        except FileNotFoundError:
            pass
    policy = resolve_cutting_policy(
        global_settings=load_config(root).get("cutting"),
        provider_settings=(provider.get("routingOverrides") or {}).get("cutting"),
        project_settings=workspace.project.get("cutting"),
    )
    return speech_dependency_bindings(workspace.project, policy.effective)
