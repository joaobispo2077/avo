"""Catalog id + physical source/runtime pins with scoped merge and preflight."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from avo.settings import resolve_path_setting, resolve_scoped_settings
from avo.stats import SECRET_KEY_MARKERS
from avo.transcribe import MODEL_FILES, default_model_root, package_version

SCOPE_ORDER = (
    "catalog",
    "global",
    "state",
    "provider",
    "registry",
    "video-state",
    "project",
    "invocation",
)
_SCOPE_RANK = {name: index for index, name in enumerate(SCOPE_ORDER)}
_SCOPE_RANK["hardware"] = _SCOPE_RANK["global"]
_BONSAI_IDS = frozenset({"bonsai-27b-gguf", "ternary-bonsai-27b-gguf"})
_URL_SECRET_KEYS = SECRET_KEY_MARKERS | {"api_key", "access_token"}
PREFLIGHT_CODES = (
    "missing_artifact",
    "incomplete_snapshot",
    "unreachable_endpoint",
    "served_name_mismatch",
    "incompatible_runtime",
    "download_disallowed",
    "secret_env_missing",
)
SupportedCompute = Callable[[str], frozenset[str] | None]
HttpGet = Callable[[str], tuple[int, str]]
SnapshotOk = Callable[[Path], bool]
DeviceOk = Callable[[str], bool]
Getenv = Callable[[str], str | None]


class PreflightError(RuntimeError):
    """Fail-closed model-source check. ``code`` is a PREFLIGHT_CODES value."""

    def __init__(self, code: str, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint


@dataclass
class ResolvedJob:
    job: str
    id: str
    pin: dict[str, Any]
    sources: dict[str, str]
    policy_hash: str
    catalog_label: str = ""
    job_key: str = ""


def job_catalog_key(job: str, label: str = "local") -> str:
    if job == "transcribe" and label == "paid":
        return "transcribe_paid"
    return job


def normalize_pin(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        return {"id": raw}
    if not isinstance(raw, Mapping):
        return None
    pin: dict[str, Any] = {}
    ident = raw.get("id") or raw.get("default")
    if ident:
        pin["id"] = str(ident)
    source = raw.get("source")
    if isinstance(source, Mapping):
        pin["source"] = _copy_source(source)
    runtime = raw.get("runtime")
    if isinstance(runtime, Mapping):
        pin["runtime"] = dict(runtime)
    return pin or None


def pin_from_document(
    doc: Mapping[str, Any] | None, job_key: str
) -> dict[str, Any] | None:
    if not doc:
        return None
    models = doc.get("models") if isinstance(doc.get("models"), Mapping) else {}
    pin = normalize_pin(models.get(job_key) if models else None)
    if pin is not None:
        return pin
    if job_key == "transcribe":
        transcription = doc.get("transcription")
        alias = (
            transcription.get("model") if isinstance(transcription, Mapping) else None
        )
        return normalize_pin(alias)
    if job_key in {"understand", "plan"} and models:
        return normalize_pin(models.get("llm"))
    return None


def invocation_from_env(env: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    env = env or os.environ
    source: dict[str, Any] = {}
    gguf = (env.get("AVO_UNDERSTAND_GGUF") or "").strip()
    mmproj = (env.get("AVO_UNDERSTAND_MMPROJ") or "").strip()
    url = (env.get("WATCHSKILL_CUSTOM_BASE_URL") or "").strip()
    served = (env.get("WATCHSKILL_SERVED_NAME") or "").strip()
    if gguf:
        source["kind"] = "artifact"
        source["artifactPath"] = gguf
    if mmproj:
        source.setdefault("companion", {})["mmproj"] = mmproj
    if url or served:
        endpoint: dict[str, str] = {}
        if url:
            endpoint["baseUrl"] = url
        if served:
            endpoint["servedName"] = served
        source["endpoint"] = endpoint
        source.setdefault("kind", "endpoint")
    return {"source": source} if source else None


def redact_endpoint(url: str) -> str:
    parts = urlsplit(url)
    netloc = parts.netloc
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[-1]
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in _URL_SECRET_KEYS or any(
            marker in lowered for marker in _URL_SECRET_KEYS
        ):
            query_pairs.append(f"{key}=***")
        else:
            query_pairs.append(f"{key}={value}" if value else key)
    return urlunsplit(
        (parts.scheme, netloc, parts.path, "&".join(query_pairs), parts.fragment)
    )


def resolve_job(
    job: str,
    *,
    root: Path | None = None,
    label: str = "local",
    project: dict[str, Any] | None = None,
    hardware_tier: dict[str, Any] | None = None,
    video_key: str | None = None,
    state: Mapping[str, Any] | None = None,
    invocation: Mapping[str, Any] | None = None,
    provider: Mapping[str, Any] | None = None,
    registry: Mapping[str, Any] | None = None,
) -> ResolvedJob:
    from avo.models import (
        catalog_option,
        format_active_model,
        load_catalog,
        load_config,
    )
    from avo.paths import repo_root

    root = repo_root(root)
    catalog = load_catalog(root)
    config = load_config(root)
    job_key = job_catalog_key(job, label)
    job_spec = (catalog.get("jobs") or {}).get(job_key) or {}
    default_id = str(job_spec.get("default") or "")
    if not job_spec:
        return ResolvedJob(
            job=job, id="", pin={}, sources={}, policy_hash="", job_key=job_key
        )

    if state is None:
        from avo import avo_state

        state = avo_state.load_state()
    provider_doc = provider if provider is not None else _load_provider(project, root)
    registry_doc = (
        registry if registry is not None else _load_registry(project, video_key, root)
    )
    video_slice = _video_slice(state, video_key)
    path_base = _path_base(project, root)

    scoped = resolve_scoped_settings(
        defaults={},
        scopes=[
            ("catalog", {"id": default_id} if default_id else None),
            ("global", pin_from_document(config, job_key)),
            ("state", pin_from_document(state, job_key)),
            ("provider", pin_from_document(provider_doc, job_key)),
            (
                "registry",
                pin_from_document(
                    registry_doc.get("defaults") if registry_doc else None, job_key
                ),
            ),
            ("video-state", pin_from_document(video_slice, job_key)),
            ("project", pin_from_document(project, job_key)),
            ("invocation", normalize_pin(invocation)),
        ],
    )
    values = dict(scoped.values)
    sources = dict(scoped.sources)
    _drop_weaker_source_fields(values, sources)
    _apply_hardware(job_key, values, sources, hardware_tier)
    _infer_and_resolve_paths(job_key, values, sources, path_base)
    option_id = str(values.get("id") or default_id)
    opt = catalog_option(catalog, job_key, option_id)
    label_text = (
        format_active_model(catalog, job_key, option_id) if option_id else option_id
    )
    pin = {
        "id": option_id,
        **(
            {"source": values["source"]}
            if isinstance(values.get("source"), Mapping)
            else {}
        ),
        **(
            {"runtime": values["runtime"]}
            if isinstance(values.get("runtime"), Mapping)
            else {}
        ),
    }
    return ResolvedJob(
        job=job,
        id=option_id,
        pin=pin,
        sources=dict(sorted(sources.items())),
        policy_hash=scoped.policy_hash,
        catalog_label=str((opt or {}).get("label") or label_text or option_id),
        job_key=job_key,
    )


def disclose_jobs(
    *,
    root: Path | None = None,
    project: dict[str, Any] | None = None,
    label: str = "local",
    hardware_tier: dict[str, Any] | None = None,
    video_key: str | None = None,
    state: Mapping[str, Any] | None = None,
    invocation: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    from avo.models import load_catalog
    from avo.paths import repo_root

    root = repo_root(root)
    catalog = load_catalog(root)
    jobs = ("transcribe", "understand", "plan")
    out: dict[str, dict[str, Any]] = {}
    for job in jobs:
        job_key = job_catalog_key(job, label if job == "transcribe" else "local")
        if job_key not in (catalog.get("jobs") or {}):
            continue
        resolved = resolve_job(
            job,
            root=root,
            label=label if job == "transcribe" else "local",
            project=project,
            hardware_tier=hardware_tier,
            video_key=video_key,
            state=state,
            invocation=invocation if job == "understand" else None,
        )
        out[job] = disclosure_for(resolved)
    if label == "paid" and "transcribe_paid" in (catalog.get("jobs") or {}):
        paid = resolve_job(
            "transcribe",
            root=root,
            label="paid",
            project=project,
            video_key=video_key,
            state=state,
        )
        out["transcribe_paid"] = disclosure_for(paid)
    return out


def disclosure_for(resolved: ResolvedJob) -> dict[str, Any]:
    source = (
        resolved.pin.get("source")
        if isinstance(resolved.pin.get("source"), Mapping)
        else {}
    )
    runtime = (
        resolved.pin.get("runtime")
        if isinstance(resolved.pin.get("runtime"), Mapping)
        else {}
    )
    endpoint = (
        source.get("endpoint") if isinstance(source.get("endpoint"), Mapping) else {}
    )
    companion = (
        source.get("companion") if isinstance(source.get("companion"), Mapping) else {}
    )
    artifact = source.get("artifactPath")
    payload: dict[str, Any] = {
        "job": resolved.job,
        "id": resolved.id,
        "catalogLabel": resolved.catalog_label,
        "scopes": resolved.sources,
        "policyHash": resolved.policy_hash,
        "device": runtime.get("device") or "auto",
        "computeType": runtime.get("computeType") or "auto",
        "offline": bool(runtime.get("offline", True)),
        "allowDownload": bool(runtime.get("allowDownload", False)),
        "reuse": _reuse_status(resolved),
    }
    if artifact:
        payload["artifactPath"] = artifact
    if source.get("cacheDir"):
        payload["cacheDir"] = source["cacheDir"]
    if companion.get("mmproj"):
        payload["companion"] = {"mmproj": companion["mmproj"]}
    if endpoint.get("baseUrl"):
        redacted = redact_endpoint(str(endpoint["baseUrl"]))
        payload["endpoint"] = {
            "origin": redacted,
            "servedName": endpoint.get("servedName") or "",
            "apiKeyEnv": endpoint.get("apiKeyEnv") or "",
        }
        payload["servedName"] = endpoint.get("servedName") or ""
    if resolved.job_key == "transcribe" or resolved.job == "transcribe":
        payload["python"] = {
            "executable": sys.executable,
            "fasterWhisper": package_version(),
        }
    return payload


def preflight(
    resolved: ResolvedJob,
    *,
    supported_compute_types: SupportedCompute | None = None,
    http_get: HttpGet | None = None,
    snapshot_complete: SnapshotOk | None = None,
    device_ok: DeviceOk | None = None,
    getenv: Getenv | None = None,
) -> None:
    getenv = getenv or os.getenv
    source = (
        resolved.pin.get("source")
        if isinstance(resolved.pin.get("source"), Mapping)
        else {}
    )
    runtime = (
        resolved.pin.get("runtime")
        if isinstance(resolved.pin.get("runtime"), Mapping)
        else {}
    )
    _preflight_runtime(runtime, supported_compute_types, device_ok)
    _preflight_python_env(runtime)
    _preflight_secret(source, getenv)
    kind = str(source.get("kind") or "")
    endpoint = (
        source.get("endpoint") if isinstance(source.get("endpoint"), Mapping) else {}
    )
    if kind == "hf-cache" or source.get("cacheDir"):
        _preflight_hf_cache(source, runtime, snapshot_complete)
    needs_artifact = bool(source.get("artifactPath")) or (
        (kind == "artifact" or resolved.job == "transcribe")
        and kind not in {"hf-cache", "endpoint"}
    )
    if needs_artifact:
        _preflight_artifact(resolved, source, runtime)
    if kind == "endpoint" or endpoint.get("baseUrl"):
        _preflight_endpoint(source, http_get)
    if resolved.id in _BONSAI_IDS:
        _preflight_bonsai(source, getenv)


def default_supported_compute_types(device: str) -> frozenset[str] | None:
    try:
        import ctranslate2

        raw = ctranslate2.get_supported_compute_types(_ct2_device(device))
        return frozenset(str(item) for item in raw)
    except Exception:
        return None


def default_device_ok(device: str) -> bool:
    if not device or device in {"auto", "cpu"}:
        return True
    if device.startswith("cuda"):
        try:
            import ctranslate2

            return int(ctranslate2.get_cuda_device_count()) > 0
        except Exception:
            return True
    return True


def check_runtime(
    device: str = "auto",
    compute_type: str = "auto",
    *,
    supported_compute_types: SupportedCompute | None = None,
    device_ok: DeviceOk | None = None,
) -> None:
    _preflight_runtime(
        {"device": device, "computeType": compute_type},
        supported_compute_types,
        device_ok,
    )


def _copy_source(source: Mapping[str, Any]) -> dict[str, Any]:
    copied = dict(source)
    if isinstance(copied.get("companion"), Mapping):
        copied["companion"] = dict(copied["companion"])
    if isinstance(copied.get("endpoint"), Mapping):
        copied["endpoint"] = dict(copied["endpoint"])
    return copied


def _path_base(project: Mapping[str, Any] | None, root: Path) -> Path:
    raw = (project or {}).get("rawDir")
    if raw:
        return Path(str(raw)).expanduser()
    return root


def _video_slice(state: Mapping[str, Any], video_key: str | None) -> dict[str, Any]:
    if not video_key:
        return {}
    from avo import avo_state

    return avo_state.get_video_state(dict(state), video_key)


def _load_provider(project: Mapping[str, Any] | None, root: Path) -> dict[str, Any]:
    slug = str((project or {}).get("provider") or "").strip()
    if not slug:
        return {}
    try:
        from avo.init_project import load_provider

        return load_provider(slug, root=root)
    except (FileNotFoundError, OSError, ValueError):
        return {}


def _load_registry(
    project: Mapping[str, Any] | None,
    video_key: str | None,
    root: Path,
) -> dict[str, Any]:
    if not video_key or ":" not in video_key:
        return {}
    provider, _, video_id = video_key.partition(":")
    slug = provider or str((project or {}).get("provider") or "")
    if not slug or not video_id:
        return {}
    try:
        from avo import video_registry

        return video_registry.load_registry(slug, video_id, root=root)
    except Exception:
        return {}


def _drop_weaker_source_fields(values: dict[str, Any], sources: dict[str, str]) -> None:
    id_rank = _SCOPE_RANK.get(sources.get("id", "catalog"), 0)
    for key in list(sources):
        if key == "id":
            continue
        if not (key in {"source", "runtime"} or key.startswith(("source.", "runtime."))):
            continue
        if _SCOPE_RANK.get(sources[key], 0) < id_rank:
            _delete_path(values, key)
            del sources[key]


def _delete_path(tree: dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    cursor: Any = tree
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            return
        cursor = cursor[part]
    if isinstance(cursor, dict):
        cursor.pop(parts[-1], None)


def _apply_hardware(
    job_key: str,
    values: dict[str, Any],
    sources: dict[str, str],
    hardware_tier: Mapping[str, Any] | None,
) -> None:
    if not hardware_tier:
        return
    id_scope = sources.get("id", "catalog")
    if id_scope not in {"catalog", "global"}:
        return
    hint = ""
    if job_key == "transcribe":
        hint = str(hardware_tier.get("whisper") or "")
    elif job_key in {"understand", "plan"}:
        hint = str(hardware_tier.get("llm") or "")
        if hint.startswith("cloud/"):
            return
    if hint:
        values["id"] = hint
        sources["id"] = "hardware"


def _infer_and_resolve_paths(
    job_key: str,
    values: dict[str, Any],
    sources: dict[str, str],
    base: Path,
) -> None:
    source = values.get("source")
    if not isinstance(source, dict):
        source = {}
    if (
        job_key == "transcribe"
        and not source.get("artifactPath")
        and not source.get("cacheDir")
    ):
        option_id = str(values.get("id") or "")
        if option_id:
            source = {
                **source,
                "kind": source.get("kind") or "artifact",
                "artifactPath": str((default_model_root() / option_id).resolve()),
            }
            values["source"] = source
            inferred = sources.get("id", "catalog")
            sources.setdefault("source", inferred)
            sources.setdefault("source.kind", inferred)
            sources.setdefault("source.artifactPath", inferred)
    if not isinstance(values.get("source"), dict):
        return
    source = values["source"]
    for key in ("artifactPath", "cacheDir"):
        if source.get(key):
            source[key] = str(
                resolve_path_setting(str(source[key]), base=base, contain=False)
            )
    companion = source.get("companion")
    if isinstance(companion, dict) and companion.get("mmproj"):
        companion["mmproj"] = str(
            resolve_path_setting(str(companion["mmproj"]), base=base, contain=False)
        )
    runtime = values.get("runtime")
    if isinstance(runtime, dict) and runtime.get("pythonEnv"):
        runtime["pythonEnv"] = str(
            resolve_path_setting(str(runtime["pythonEnv"]), base=base, contain=False)
        )


def _reuse_status(resolved: ResolvedJob) -> str:
    source = (
        resolved.pin.get("source")
        if isinstance(resolved.pin.get("source"), Mapping)
        else {}
    )
    runtime = (
        resolved.pin.get("runtime")
        if isinstance(resolved.pin.get("runtime"), Mapping)
        else {}
    )
    path = Path(str(source.get("artifactPath") or source.get("cacheDir") or ""))
    present = path.is_dir() or path.is_file()
    if runtime.get("allowDownload") and present:
        return "downloaded-approved"
    return "existing"


def _ct2_device(device: str) -> str:
    if device.startswith("cuda"):
        return "cuda"
    return "cpu" if device == "cpu" else "auto"


def _preflight_runtime(
    runtime: Mapping[str, Any],
    supported_compute_types: SupportedCompute | None,
    device_ok: DeviceOk | None,
) -> None:
    device = str(runtime.get("device") or "auto")
    compute = str(runtime.get("computeType") or "auto")
    probe_device = device_ok or default_device_ok
    if device not in {"auto", ""} and not probe_device(device):
        raise PreflightError(
            "incompatible_runtime",
            f"{device} is not supported on this machine",
            hint="set runtime.device to auto or cpu, or fix the GPU install",
        )
    if compute in {"", "auto"}:
        return
    probe = supported_compute_types or default_supported_compute_types
    supported = probe(device)
    if supported is not None and compute not in supported:
        raise PreflightError(
            "incompatible_runtime",
            f"{compute} is not supported here (device={device})",
            hint="use runtime.computeType auto or a type CTranslate2 lists for this device",
        )


def _preflight_python_env(runtime: Mapping[str, Any]) -> None:
    env_path = runtime.get("pythonEnv")
    if not env_path:
        return
    if not Path(str(env_path)).expanduser().exists():
        raise PreflightError(
            "missing_artifact",
            f"pythonEnv path is missing: {env_path}",
            hint="point runtime.pythonEnv at an existing interpreter",
        )


def _preflight_secret(source: Mapping[str, Any], getenv: Getenv) -> None:
    endpoint = (
        source.get("endpoint") if isinstance(source.get("endpoint"), Mapping) else {}
    )
    name = str(endpoint.get("apiKeyEnv") or "").strip()
    if not name:
        return
    if not (getenv(name) or "").strip():
        raise PreflightError(
            "secret_env_missing",
            f"Set env {name} (value never printed)",
            hint=f"export {name} before running this job",
        )


def _preflight_hf_cache(
    source: Mapping[str, Any],
    runtime: Mapping[str, Any],
    snapshot_complete: SnapshotOk | None,
) -> None:
    cache = Path(str(source.get("cacheDir") or ""))
    if not cache.exists():
        _missing_or_download(cache, runtime, "Hugging Face cache")
        return
    check = snapshot_complete or _default_snapshot_complete
    if not check(cache):
        raise PreflightError(
            "incomplete_snapshot",
            f"cache incomplete for this revision at {cache}",
            hint="re-prepare with network or point at a full directory",
        )


def _default_snapshot_complete(path: Path) -> bool:
    if not path.exists():
        return False
    return not any(path.rglob("*.incomplete"))


def _preflight_artifact(
    resolved: ResolvedJob,
    source: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> None:
    artifact = Path(str(source.get("artifactPath") or ""))
    if resolved.job == "transcribe" or resolved.job_key == "transcribe":
        explicit = resolved.sources.get("source.artifactPath") not in {
            None,
            "catalog",
            "global",
            "hardware",
        }
        if not artifact.exists():
            _missing_or_download(
                artifact, runtime, "transcribe model", explicit=explicit
            )
            return
        missing = [name for name in MODEL_FILES if not (artifact / name).is_file()]
        if missing:
            _missing_or_download(
                artifact,
                runtime,
                f"transcribe model (missing {', '.join(missing)})",
                explicit=explicit,
            )
        return
    if source.get("artifactPath") and not artifact.exists():
        raise PreflightError(
            "missing_artifact",
            f"Named path missing: {artifact}",
            hint="fix the pin or prepare the file",
        )
    companion = (
        source.get("companion") if isinstance(source.get("companion"), Mapping) else {}
    )
    mmproj = companion.get("mmproj")
    if mmproj and not Path(str(mmproj)).is_file():
        raise PreflightError(
            "missing_artifact",
            f"Named path missing: {mmproj}",
            hint="set source.companion.mmproj to an existing vision projector",
        )


def _missing_or_download(
    path: Path,
    runtime: Mapping[str, Any],
    label: str,
    *,
    explicit: bool = False,
) -> None:
    allow = bool(runtime.get("allowDownload"))
    offline = bool(runtime.get("offline", True))
    if explicit:
        raise PreflightError(
            "missing_artifact",
            f"Named path missing: {path}",
            hint="fix the pin or prepare the file",
        )
    if offline or not allow:
        raise PreflightError(
            "download_disallowed",
            f"Model not prepared at {path}; run prepare",
            hint="python -m avo.prepare_transcription or set allowDownload after a manual fetch",
        )
    raise PreflightError(
        "missing_artifact",
        f"{label} missing at {path}",
        hint="prepare the artifact, then retry",
    )


def _preflight_endpoint(source: Mapping[str, Any], http_get: HttpGet | None) -> None:
    endpoint = (
        source.get("endpoint") if isinstance(source.get("endpoint"), Mapping) else {}
    )
    base = str(endpoint.get("baseUrl") or "").rstrip("/")
    if not base:
        return
    served = str(endpoint.get("servedName") or "").strip()
    url = f"{base}/models"
    getter = http_get or _default_http_get
    try:
        status, body = getter(url)
    except Exception:
        raise PreflightError(
            "unreachable_endpoint",
            f"Cannot reach {redact_endpoint(base)}",
            hint="start the OpenAI-compatible server and retry",
        ) from None
    if status >= 400:
        raise PreflightError(
            "unreachable_endpoint",
            f"Cannot reach {redact_endpoint(base)}",
            hint="start the OpenAI-compatible server and retry",
        )
    if not served:
        return
    names = _listed_model_ids(body)
    if names and served not in names:
        raise PreflightError(
            "served_name_mismatch",
            f"Server has no {served}",
            hint="set source.endpoint.servedName to a name the server lists",
        )


def _listed_model_ids(body: str) -> list[str]:
    try:
        payload = json.loads(body)
    except ValueError:
        return []
    rows = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return []
    names = [
        str(row.get("id")) for row in rows if isinstance(row, Mapping) and row.get("id")
    ]
    return names


def _default_http_get(url: str) -> tuple[int, str]:
    request = Request(url, method="GET")
    with urlopen(request, timeout=2.0) as response:
        status = int(getattr(response, "status", 200) or 200)
        return status, response.read().decode("utf-8", errors="replace")


def _preflight_bonsai(source: Mapping[str, Any], getenv: Getenv) -> None:
    artifact = str(
        source.get("artifactPath") or getenv("AVO_UNDERSTAND_GGUF") or ""
    ).strip()
    companion = (
        source.get("companion") if isinstance(source.get("companion"), Mapping) else {}
    )
    mmproj = str(
        companion.get("mmproj") or getenv("AVO_UNDERSTAND_MMPROJ") or ""
    ).strip()
    endpoint = (
        source.get("endpoint") if isinstance(source.get("endpoint"), Mapping) else {}
    )
    url = str(
        endpoint.get("baseUrl") or getenv("WATCHSKILL_CUSTOM_BASE_URL") or ""
    ).strip()
    cheap = (getenv("WATCHSKILL_VISION_CHEAP_PROVIDER") or "").strip()
    strong = (getenv("WATCHSKILL_VISION_STRONG_PROVIDER") or "").strip()
    if not artifact or not Path(artifact).is_file():
        raise PreflightError(
            "missing_artifact",
            "Named path missing: Bonsai GGUF (source.artifactPath or AVO_UNDERSTAND_GGUF)",
            hint="download the language GGUF and pin the file",
        )
    if not mmproj or not Path(mmproj).is_file():
        raise PreflightError(
            "missing_artifact",
            "Named path missing: Bonsai mmproj (source.companion.mmproj or AVO_UNDERSTAND_MMPROJ)",
            hint="pin the vision mmproj beside the language GGUF",
        )
    if not url and cheap != "custom" and strong != "custom":
        raise PreflightError(
            "unreachable_endpoint",
            "Cannot reach Bonsai vision endpoint (no baseUrl or WATCHSKILL custom provider)",
            hint="start llama-server and set source.endpoint.baseUrl",
        )
