"""Provider-scoped video registry stubs under providers/<slug>/videos/<id>/.

Registry entries are path-only metadata in-repo. Workflow roots stay external.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from avo import avo_state
from avo.paths import providers_dir, repo_root, schema_path
from avo.session import normalize_path

VIDEO_SCHEMA = schema_path("avo.video.schema.json")
REGISTRY_FILENAME = "video.json"
INDEX_FILENAME = "videos.index.json"
VIDEO_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PROVIDER_SLUG_PATTERN = re.compile(r"^[a-z0-9_][a-z0-9-]*$")


class VideoRegistryError(ValueError):
    """Invalid registry entry or path."""


def _providers_base(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root) / "providers"
    return providers_dir()


def provider_videos_dir(provider: str, *, root: Path | None = None) -> Path:
    slug = _validate_slug(provider, "provider")
    return _providers_base(root) / slug / "videos"


def video_entry_dir(provider: str, video_id: str, *, root: Path | None = None) -> Path:
    slug = _validate_slug(provider, "provider")
    vid = _validate_slug(video_id, "video id")
    return _providers_base(root) / slug / "videos" / vid


def registry_path(provider: str, video_id: str, *, root: Path | None = None) -> Path:
    return video_entry_dir(provider, video_id, root=root) / REGISTRY_FILENAME


def _validate_slug(value: str, label: str) -> str:
    slug = str(value or "").strip()
    pattern = PROVIDER_SLUG_PATTERN if label == "provider" else VIDEO_ID_PATTERN
    if not slug or not pattern.fullmatch(slug):
        raise VideoRegistryError(f"invalid {label}: {value!r}")
    return slug


def is_under_repo(path: Path, *, root: Path | None = None) -> bool:
    base = (root or repo_root()).resolve()
    try:
        path.expanduser().resolve().relative_to(base)
        return True
    except ValueError:
        return False


def validate_external_raw_dir(raw_dir: str | Path, *, root: Path | None = None) -> Path:
    path = Path(str(raw_dir)).expanduser()
    if not path.is_absolute():
        raise VideoRegistryError(f"rawDir must be an absolute external path: {raw_dir!r}")
    resolved = path.resolve()
    if is_under_repo(resolved, root=root):
        raise VideoRegistryError(
            f"rawDir must not be inside the AVO repo: {resolved}"
        )
    return resolved


def build_registry(
    provider: str,
    video_id: str,
    raw_dir: str | Path,
    *,
    title: str = "",
    status: str = "in-progress",
    created_at: str | None = None,
) -> dict[str, Any]:
    slug = _validate_slug(provider, "provider")
    vid = _validate_slug(video_id, "video id")
    resolved = validate_external_raw_dir(raw_dir)
    if status not in {"in-progress", "completed", "archived"}:
        raise VideoRegistryError(f"invalid status: {status!r}")

    payload: dict[str, Any] = {
        "$schema": "../../../schemas/avo.video.schema.json",
        "id": vid,
        "provider": slug,
        "rawDir": normalize_path(resolved),
        "status": status,
        "createdAt": created_at or avo_state.now_iso(),
        "projectFile": "avo.project.json",
    }
    if title.strip():
        payload["title"] = title.strip()
    return payload


def write_registry(
    provider: str,
    video_id: str,
    raw_dir: str | Path,
    *,
    title: str = "",
    status: str = "in-progress",
    root: Path | None = None,
    overwrite: bool = False,
) -> Path:
    entry_dir = video_entry_dir(provider, video_id, root=root)
    out = entry_dir / REGISTRY_FILENAME
    if out.exists() and not overwrite:
        raise VideoRegistryError(f"registry already exists: {out}")

    payload = build_registry(provider, video_id, raw_dir, title=title, status=status)
    entry_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rebuild_index(provider, root=root)
    return out


def load_registry(provider: str, video_id: str, *, root: Path | None = None) -> dict[str, Any]:
    path = registry_path(provider, video_id, root=root)
    if not path.is_file():
        raise FileNotFoundError(f"video registry not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _validate_registry_payload(payload, provider, video_id)
    return payload


def _validate_registry_payload(payload: dict[str, Any], provider: str, video_id: str) -> None:
    if payload.get("provider") != provider:
        raise VideoRegistryError(
            f"registry provider mismatch: expected {provider!r}, got {payload.get('provider')!r}"
        )
    if payload.get("id") != video_id:
        raise VideoRegistryError(
            f"registry id mismatch: expected {video_id!r}, got {payload.get('id')!r}"
        )
    validate_external_raw_dir(payload.get("rawDir") or "")


def list_videos(provider: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    base = provider_videos_dir(provider, root=root)
    if not base.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        reg = child / REGISTRY_FILENAME
        if not reg.is_file():
            continue
        try:
            payload = json.loads(reg.read_text(encoding="utf-8"))
            _validate_registry_payload(payload, provider, child.name)
        except (OSError, json.JSONDecodeError, VideoRegistryError):
            continue
        entries.append(payload)
    return entries


def resolve_raw_dir(
    provider: str,
    video_id: str,
    *,
    root: Path | None = None,
) -> Path:
    payload = load_registry(provider, video_id, root=root)
    return Path(str(payload["rawDir"])).expanduser().resolve()


def rebuild_index(provider: str, *, root: Path | None = None) -> Path:
    slug = _validate_slug(provider, "provider")
    entries = list_videos(slug, root=root)
    index_path = _providers_base(root) / slug / INDEX_FILENAME
    index = {
        "provider": slug,
        "updatedAt": avo_state.now_iso(),
        "videos": [
            {
                "id": item["id"],
                "rawDir": item["rawDir"],
                "title": item.get("title", ""),
                "status": item.get("status", "in-progress"),
            }
            for item in entries
        ],
    }
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return index_path


def update_status(
    provider: str,
    video_id: str,
    status: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    path = registry_path(provider, video_id, root=root)
    payload = load_registry(provider, video_id, root=root)
    if status not in {"in-progress", "completed", "archived"}:
        raise VideoRegistryError(f"invalid status: {status!r}")
    payload["status"] = status
    payload["updatedAt"] = avo_state.now_iso()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rebuild_index(provider, root=root)
    return payload


def find_video_by_raw_dir(
    raw_dir: str | Path,
    *,
    provider: str = "",
    root: Path | None = None,
) -> dict[str, Any] | None:
    target = normalize_path(Path(str(raw_dir)).expanduser())
    providers = [provider] if provider else _providers_with_videos(root=root)
    for slug in providers:
        for entry in list_videos(slug, root=root):
            if normalize_path(Path(str(entry["rawDir"]))) == target:
                return entry
    return None


def _providers_with_videos(*, root: Path | None = None) -> list[str]:
    base = _providers_base(root)
    if not base.is_dir():
        return []
    slugs: list[str] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if (child / "videos").is_dir():
            slugs.append(child.name)
    return slugs
