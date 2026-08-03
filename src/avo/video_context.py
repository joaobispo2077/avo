"""Unified video context resolution for parallelism and concurrency work modes."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from avo import avo_state, video_registry
from avo.init_project import load_config, load_provider
from avo.paths import repo_root
from avo.project_inventory import load_project
from avo.session import normalize_path

LOCK_FILENAME = ".avo-lock.json"


@dataclass
class VideoContext:
    provider: str
    video_id: str | None
    raw_dir: Path
    video_key: str | None
    registry: dict[str, Any] | None = None
    project: dict[str, Any] = field(default_factory=dict)


def make_video_key(provider: str, video_id: str) -> str:
    return avo_state.video_state_key(provider, video_id)


def lock_path(raw_dir: Path) -> Path:
    return Path(raw_dir).expanduser().resolve() / "edit" / LOCK_FILENAME


def resolve_context(
    *,
    provider: str = "",
    video_id: str = "",
    raw_dir: str | Path = "",
    root: Path | None = None,
) -> VideoContext:
    """Resolve provider + video id and/or rawDir into a VideoContext."""
    root = repo_root(root)
    slug = provider.strip()
    vid = video_id.strip()
    registry: dict[str, Any] | None = None
    resolved_raw: Path | None = None

    if slug and vid:
        registry = video_registry.load_registry(slug, vid, root=root)
        resolved_raw = Path(str(registry["rawDir"])).expanduser().resolve()
    elif raw_dir:
        resolved_raw = Path(str(raw_dir)).expanduser().resolve()
        if not slug:
            project = load_project(resolved_raw)
            slug = str(project.get("provider") or "").strip()
        if slug and not vid:
            found = video_registry.find_video_by_raw_dir(resolved_raw, provider=slug, root=root)
            if found:
                vid = str(found.get("id") or "")
                registry = found
    else:
        active = avo_state.load_active_context()
        if active:
            slug = str(active.get("provider") or slug).strip()
            vid = str(active.get("videoId") or vid).strip()
            if slug and vid:
                return resolve_context(provider=slug, video_id=vid, root=root)

    if resolved_raw is None:
        raise video_registry.VideoRegistryError(
            "video context requires --provider + --video-id, --raw-dir, or active context"
        )

    project = load_project(resolved_raw)
    if not slug and project.get("provider"):
        slug = str(project["provider"])

    key = make_video_key(slug, vid) if slug and vid else None
    return VideoContext(
        provider=slug,
        video_id=vid or None,
        raw_dir=resolved_raw,
        video_key=key,
        registry=registry,
        project=project,
    )


def merge_config(ctx: VideoContext, root: Path | None = None) -> dict[str, Any]:
    """Merge avo.config → provider → registry defaults → project (later wins)."""
    root = repo_root(root)
    merged: dict[str, Any] = dict(load_config(root))
    if ctx.provider:
        try:
            provider_manifest = load_provider(ctx.provider, root=root)
            for key in ("transcription", "models", "assets"):
                if provider_manifest.get(key):
                    merged[key] = {
                        **(merged.get(key) or {}),
                        **provider_manifest[key],
                    }
        except FileNotFoundError:
            pass
    if ctx.registry:
        defaults = ctx.registry.get("defaults") or {}
        for key in ("transcription", "models"):
            if defaults.get(key):
                merged[key] = {**(merged.get(key) or {}), **defaults[key]}
    for key in ("transcription", "models", "assets", "approvalGates", "deliverable"):
        if ctx.project.get(key):
            merged[key] = {**(merged.get(key) or {}), **ctx.project[key]}
    return merged


def read_lock(raw_dir: Path) -> dict[str, Any] | None:
    path = lock_path(raw_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def acquire_lock(
    ctx: VideoContext,
    *,
    force: bool = False,
    session_id: str = "",
) -> Path:
    edit_dir = ctx.raw_dir / "edit"
    edit_dir.mkdir(parents=True, exist_ok=True)
    path = lock_path(ctx.raw_dir)
    existing = read_lock(ctx.raw_dir)
    if existing and not force:
        raise video_registry.VideoRegistryError(
            f"advisory lock already held: {path} (use --force to replace)"
        )
    payload = {
        "provider": ctx.provider,
        "videoId": ctx.video_id,
        "rawDir": normalize_path(ctx.raw_dir),
        "videoKey": ctx.video_key,
        "sessionId": session_id,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "acquiredAt": avo_state.now_iso(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def release_lock(raw_dir: Path) -> bool:
    path = lock_path(raw_dir)
    if path.is_file():
        path.unlink()
        return True
    return False


def work_mode_advisory(provider: str, *, root: Path | None = None) -> str:
    """Return human advisory for parallelism vs concurrency when multiple videos are active."""
    entries = video_registry.list_videos(provider, root=root)
    in_progress = [e for e in entries if e.get("status") == "in-progress"]
    count = len(in_progress)
    if count <= 1:
        return "One video in progress — any work mode is fine."
    lines = [
        f"{count} videos in progress for provider '{provider}'.",
        "Recommended: parallelism — one Cursor chat per video.",
        "Concurrency (same chat, multiple videos) is supported but discouraged.",
    ]
    try:
        from avo.models import _hardware_tier

        tier = _hardware_tier(repo_root(root))
        if tier and tier.get("tier") in ("minimal", "low"):
            lines.append(
                "Hardware tier is modest — avoid concurrent renders in one chat; "
                "prefer one chat per video."
            )
    except Exception:
        pass
    return " ".join(lines)
