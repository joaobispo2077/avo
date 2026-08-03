"""Resolve active models from catalog, config, state, project, and hardware advisory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avo.paths import config_path, repo_root

try:
    from avo import avo_state
except ImportError:
    from avo import avo_state  # type: ignore[assignment]

CATALOG_FILE = "avo.model-catalog.json"
CONFIG_FILE = "avo.config.json"
SPEED_ORDER = ["fastest", "fast", "balanced", "slow", "slowest"]
QUALITY_ORDER = ["low", "fair", "good", "high", "best"]


def _config_at(root: Path, name: str) -> Path:
    """Resolve a config manifest under root, preferring config/ when present."""
    nested = root / "config" / name
    if nested.is_file():
        return nested
    return root / name


def load_catalog(root: Path | None = None) -> dict[str, Any]:
    root = repo_root(root)
    if root.resolve() == repo_root().resolve():
        path = config_path(CATALOG_FILE)
    else:
        path = _config_at(root, CATALOG_FILE)
    if not path.is_file():
        raise FileNotFoundError(f"missing model catalog: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_config(root: Path | None = None) -> dict[str, Any]:
    root = repo_root(root)
    if root.resolve() == repo_root().resolve():
        path = config_path(CONFIG_FILE)
    else:
        path = _config_at(root, CONFIG_FILE)
    return json.loads(path.read_text(encoding="utf-8"))


def _job_catalog_key(job: str, label: str = "local") -> str:
    if job == "transcribe" and label == "paid":
        return "transcribe_paid"
    return job


def _option_index(options: list[dict[str, Any]], option_id: str) -> int:
    for i, opt in enumerate(options):
        if opt.get("id") == option_id:
            return i
    return -1


def catalog_option(catalog: dict[str, Any], job_key: str, option_id: str) -> dict[str, Any] | None:
    job_spec = (catalog.get("jobs") or {}).get(job_key)
    if not job_spec:
        return None
    for opt in job_spec.get("options") or []:
        if opt.get("id") == option_id:
            return opt
    return None


def format_active_model(catalog: dict[str, Any], job_key: str, option_id: str) -> str:
    job_spec = (catalog.get("jobs") or {}).get(job_key) or {}
    adapter = job_spec.get("adapter", job_key)
    opt = catalog_option(catalog, job_key, option_id)
    label = opt.get("label") if opt else option_id
    if job_key == "transcribe":
        return f"{adapter}:{option_id}"
    return str(label or option_id)


@dataclass
class ModelAlternatives:
    job: str
    current_id: str
    current: dict[str, Any]
    lighter: list[dict[str, Any]]
    heavier: list[dict[str, Any]]
    all_options: list[dict[str, Any]]


def resolve_option_id(
    job: str,
    *,
    root: Path | None = None,
    label: str = "local",
    project: dict[str, Any] | None = None,
    hardware_tier: dict[str, Any] | None = None,
    video_key: str | None = None,
) -> str:
    root = repo_root(root)
    catalog = load_catalog(root)
    config = load_config(root)
    job_key = _job_catalog_key(job, label)
    job_spec = (catalog.get("jobs") or {}).get(job_key)
    if not job_spec:
        return ""

    default_id = job_spec.get("default", "")
    models_cfg = (config.get("models") or {}).get(job_key) or {}
    if isinstance(models_cfg, str):
        configured = models_cfg
    else:
        configured = models_cfg.get("default") or default_id

    state = avo_state.load_state()
    state_models = state.get("models") or {}
    video_slice = avo_state.get_video_state(state, video_key) if video_key else {}
    video_transcription = video_slice.get("transcription") or {}
    video_models = video_slice.get("models") or {}

    if job_key == "transcribe":
        project_model = ((project or {}).get("transcription") or {}).get("model")
        if project_model:
            return str(project_model)
        if video_key and video_transcription.get("model"):
            return str(video_transcription["model"])
        state_model = (state.get("transcription") or {}).get("model") or state_models.get("transcribe")
        if state_model and not video_key:
            return str(state_model)
        if hardware_tier and hardware_tier.get("whisper"):
            return str(hardware_tier["whisper"])
        return str(configured or default_id)

    if job_key in ("understand", "plan"):
        project_models = (project or {}).get("models") or {}
        if project_models.get(job_key):
            return str(project_models[job_key])
        if video_key and video_models.get(job_key):
            return str(video_models[job_key])
        state_llm = state_models.get(job_key) or state_models.get("llm")
        if state_llm and not video_key:
            return str(state_llm)
        if hardware_tier and hardware_tier.get("llm"):
            llm = str(hardware_tier["llm"])
            if llm.startswith("cloud/"):
                return str(configured or default_id)
            return llm
        override = models_cfg.get("default") if isinstance(models_cfg, dict) else configured
        return str(override or default_id)

    return str(configured or default_id)


def resolve_active_models(
    root: Path | None = None,
    *,
    project: dict[str, Any] | None = None,
    label: str = "local",
    hardware_tier: dict[str, Any] | None = None,
    video_key: str | None = None,
) -> dict[str, str]:
    root = repo_root(root)
    catalog = load_catalog(root)
    if hardware_tier is None:
        hardware_tier = _hardware_tier(root)

    out: dict[str, str] = {}
    for job in ("transcribe", "understand", "plan"):
        job_key = _job_catalog_key(job, label if job == "transcribe" else "local")
        if job_key not in (catalog.get("jobs") or {}):
            continue
        option_id = resolve_option_id(
            job,
            root=root,
            label=label if job == "transcribe" else "local",
            project=project,
            hardware_tier=hardware_tier,
            video_key=video_key,
        )
        out[job] = format_active_model(catalog, job_key, option_id)
    if label == "paid":
        paid_key = "transcribe_paid"
        if paid_key in (catalog.get("jobs") or {}):
            pid = resolve_option_id(
                "transcribe",
                root=root,
                label="paid",
                project=project,
                video_key=video_key,
            )
            out["transcribe_paid"] = format_active_model(catalog, paid_key, pid)
    return out


def list_alternatives(
    job: str,
    *,
    root: Path | None = None,
    label: str = "local",
    project: dict[str, Any] | None = None,
) -> ModelAlternatives:
    root = repo_root(root)
    catalog = load_catalog(root)
    job_key = _job_catalog_key(job, label)
    job_spec = (catalog.get("jobs") or {}).get(job_key)
    if not job_spec:
        raise KeyError(f"unknown catalog job: {job_key}")
    options: list[dict[str, Any]] = list(job_spec.get("options") or [])
    current_id = resolve_option_id(job, root=root, label=label, project=project)
    idx = _option_index(options, current_id)
    current = options[idx] if idx >= 0 else {"id": current_id, "label": current_id}

    def weight_key(opt: dict[str, Any]) -> tuple[int, int]:
        speed = opt.get("speed", "balanced")
        quality = opt.get("quality", "good")
        si = SPEED_ORDER.index(speed) if speed in SPEED_ORDER else 2
        qi = QUALITY_ORDER.index(quality) if quality in QUALITY_ORDER else 2
        return (si, qi)

    lighter = [o for i, o in enumerate(options) if i < idx] if idx >= 0 else []
    heavier = [o for i, o in enumerate(options) if i > idx] if idx >= 0 else []
    if idx < 0:
        cw = weight_key(current)
        lighter = [o for o in options if weight_key(o) < cw]
        heavier = [o for o in options if weight_key(o) > cw]

    return ModelAlternatives(
        job=job_key,
        current_id=current_id,
        current=current,
        lighter=lighter,
        heavier=heavier,
        all_options=options,
    )


def _hardware_tier(root: Path) -> dict[str, Any] | None:
    try:
        from avo.hardware import gather, suggest_tier_catalog
    except ImportError:
        try:
            from avo.hardware import gather, suggest_tier_catalog
        except ImportError:
            try:
                from hardware import gather, suggest_tier_catalog  # type: ignore
            except ImportError:
                return None
    report = gather(root)
    return suggest_tier_catalog(report, root=root)


def format_disclosure_line(alt: ModelAlternatives) -> str:
    cur = alt.current
    parts = [
        f"{cur.get('label', alt.current_id)}",
        f"speed={cur.get('speed', '?')}",
        f"quality={cur.get('quality', '?')}",
    ]
    if cur.get("vramMB"):
        parts.append(f"~{cur['vramMB']}MB VRAM")
    if cur.get("diskMB"):
        parts.append(f"~{cur['diskMB']}MB disk")
    line = " | ".join(parts)
    if alt.lighter:
        lite = alt.lighter[-1]
        line += f" | lighter: {lite.get('label')} ({lite.get('speed')})"
    if alt.heavier:
        heavy = alt.heavier[0]
        line += f" | heavier: {heavy.get('label')} ({heavy.get('quality')})"
    return line


def disclosure_summary(root: Path | None = None) -> str:
    root = repo_root(root)
    lines = ["AVO active models (advisory — say the word to change):"]
    for job in ("transcribe", "understand", "plan"):
        try:
            alt = list_alternatives(job, root=root)
            lines.append(f"  {job}: {format_disclosure_line(alt)}")
        except KeyError:
            continue
    return "\n".join(lines)
