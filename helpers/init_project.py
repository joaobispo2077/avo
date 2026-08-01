"""Bootstrap a per-video AVO project (avo.project.json).

Declares the inputs AVO works from — the raw-files folder plus optional
SFX / music / inserts / graphics / logos — and the provider whose brand and
defaults apply. Empty project fields inherit the provider manifest
(providers/<provider>/avo.provider.json); transcription language falls back to
the provider, then to avo.config.json.

The project file lives EXTERNALLY, next to the raw footage (in rawDir), not in
this repo. Cross-platform: uses pathlib, no hardcoded separators.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ASSET_KEYS = ("sfx", "music", "inserts", "graphics", "logos")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def providers_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "providers"


def list_providers(root: Path | None = None) -> list[str]:
    base = providers_dir(root)
    if not base.is_dir():
        return []
    names = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if (child / "avo.provider.json").is_file():
            names.append(child.name)
    return names


def load_provider(slug: str, root: Path | None = None) -> dict[str, Any]:
    manifest = providers_dir(root) / slug / "avo.provider.json"
    if not manifest.is_file():
        available = ", ".join(list_providers(root)) or "(none)"
        raise FileNotFoundError(
            f"provider '{slug}' not found at {manifest}. Available: {available}. "
            f"Create one with scripts/new-provider.sh / new-provider.ps1."
        )
    return json.loads(manifest.read_text(encoding="utf-8"))


def load_config(root: Path | None = None) -> dict[str, Any]:
    path = (root or repo_root()) / "avo.config.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_project(
    provider_slug: str,
    raw_dir: str,
    *,
    title: str = "",
    asset_overrides: dict[str, str] | None = None,
    language: str = "",
    provider_manifest: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_manifest = provider_manifest or {}
    config = config or {}
    asset_overrides = asset_overrides or {}

    provider_assets = provider_manifest.get("assets", {}) or {}
    assets: dict[str, str] = {}
    for key in ASSET_KEYS:
        override = (asset_overrides.get(key) or "").strip()
        assets[key] = override or str(provider_assets.get(key, "") or "")
    if not assets["logos"]:
        assets["logos"] = f"providers/{provider_slug}/logo"

    resolved_language = (
        language.strip()
        or (provider_manifest.get("transcription", {}) or {}).get("language", "")
        or (config.get("transcription", {}) or {}).get("language", "")
    )

    project: dict[str, Any] = {
        "$schema": "./avo.project.schema.json",
        "provider": provider_slug,
        "rawDir": raw_dir,
    }
    if title.strip():
        project["title"] = title.strip()
    project["assets"] = assets
    if resolved_language and resolved_language != "<set-at-setup>":
        project["transcription"] = {"language": resolved_language}
    return project


def _prompt(message: str, default: str = "", interactive: bool = True) -> str:
    if not interactive:
        return default
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{message}{suffix}: ").strip()
    except EOFError:
        return default
    return answer or default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap a per-video AVO project (avo.project.json)."
    )
    parser.add_argument("--provider", default="", help="Provider slug (must exist under providers/).")
    parser.add_argument("--raw-dir", default="", help="External raw-files folder (workflow root).")
    parser.add_argument("--title", default="", help="Optional working title.")
    parser.add_argument("--sfx", default="")
    parser.add_argument("--music", default="")
    parser.add_argument("--inserts", default="")
    parser.add_argument("--graphics", default="")
    parser.add_argument("--logos", default="")
    parser.add_argument("--lang", default="", help="Transcription language override.")
    parser.add_argument("--print", action="store_true", dest="print_only",
                        help="Print the project JSON to stdout instead of writing it.")
    parser.add_argument("--yes", "-y", action="store_true", help="Non-interactive; use provided/defaults only.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    interactive = sys.stdin.isatty() and not args.yes

    provider_slug = args.provider or _prompt(
        "Provider slug", "", interactive
    )
    if not provider_slug:
        available = ", ".join(list_providers()) or "(none)"
        print(f"error: --provider is required. Available: {available}", file=sys.stderr)
        return 2

    try:
        provider_manifest = load_provider(provider_slug)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    raw_dir = args.raw_dir or _prompt(
        "External raw-files folder (workflow root)", "", interactive
    )
    if not raw_dir:
        print("error: --raw-dir is required", file=sys.stderr)
        return 2

    title = args.title or _prompt("Working title (optional)", "", interactive)

    asset_overrides = {
        "sfx": args.sfx,
        "music": args.music,
        "inserts": args.inserts,
        "graphics": args.graphics,
        "logos": args.logos,
    }
    if interactive:
        for key in ("sfx", "music", "inserts", "graphics"):
            if not asset_overrides[key]:
                asset_overrides[key] = _prompt(f"{key} path (optional)", "", interactive)

    project = build_project(
        provider_slug,
        raw_dir,
        title=title,
        asset_overrides=asset_overrides,
        language=args.lang,
        provider_manifest=provider_manifest,
        config=load_config(),
    )

    text = json.dumps(project, indent=2, ensure_ascii=False) + "\n"

    if args.print_only:
        sys.stdout.write(text)
        return 0

    target = Path(raw_dir).expanduser()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot create raw dir {target}: {exc}", file=sys.stderr)
        return 1
    out = target / "avo.project.json"
    if out.exists():
        print(f"error: {out} already exists (refusing to overwrite)", file=sys.stderr)
        return 1
    out.write_text(text, encoding="utf-8")
    print(f"Created project: {out}")
    print(f"  provider : {provider_slug} ({provider_manifest.get('kind', '?')})")
    print(f"  rawDir   : {raw_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
