"""Provider design-token resolution for Shorts compositions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from avo import shorts_contract


def _palette_to_tokens(palette: Mapping[str, Any]) -> dict[str, str]:
    roles = palette.get("roles") or {}
    return {
        "ink": str(roles.get("captionFill") or palette.get("text") or "#fff8f0"),
        "rail": str(roles.get("captionRail") or palette.get("secondary") or "rgba(14, 12, 18, 0.88)"),
        "accent": str(palette.get("accent") or "#ffd21f"),
        "punch": str(roles.get("punch") or palette.get("accent") or "#ff5b45"),
        "font": str(roles.get("font") or "sans-serif"),
        "railWidth": str(roles.get("railWidth") or "920px"),
    }


def load_provider_design_tokens(provider: str, *, root: Path | None = None) -> dict[str, str]:
    """Load HyperFrames caption tokens from the active provider palette."""
    try:
        from avo.init_project import load_provider
        from avo.paths import repo_root

        manifest = load_provider(provider, root=root or repo_root())
    except (FileNotFoundError, ValueError, OSError):
        return {}
    palette_rel = (manifest.get("brand") or {}).get("palette")
    if not palette_rel:
        return {}
    base = root or __import__("avo.paths", fromlist=["repo_root"]).repo_root()
    palette_path = (base / palette_rel).resolve()
    if not palette_path.is_file():
        return {}
    try:
        palette = json.loads(palette_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _palette_to_tokens(palette)


def provider_tokens_fingerprint(tokens: Mapping[str, Any] | None) -> str | None:
    if not tokens:
        return None
    return shorts_contract.content_hash({"providerTokens": dict(tokens)})
