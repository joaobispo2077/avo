"""Create provider workspaces from the repository template."""
from __future__ import annotations
import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from avo.paths import repo_root

VALID_KINDS = ("youtube", "tiktok", "instagram", "x", "podcast", "shorts", "generic")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

def build_manifest(name: str, kind: str, raw_root: str, *, sfx: str = "", music: str = "", inserts: str = "", graphics: str = "", language: str = "en") -> dict[str, Any]:
    if not _SLUG.fullmatch(name):
        raise ValueError("name must use lowercase letters, digits, and hyphens")
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(VALID_KINDS)}")
    if not raw_root.strip():
        raise ValueError("raw_root is required")
    return {
        "$schema": "../avo.provider.schema.json", "name": name, "displayName": name,
        "kind": kind, "description": "", "media": {"rawRoot": raw_root},
        "assets": {"sfx": sfx, "music": music, "inserts": inserts, "graphics": graphics, "logos": f"providers/{name}/logo"},
        "transcription": {"language": language},
        "brand": {"design": f"providers/{name}/DESIGN.md", "palette": f"providers/{name}/brand/palette.json"},
        "routingOverrides": {},
        "animationLibrary": "animations/animation.json",
    }

def scaffold_provider(root: Path, manifest: dict[str, Any]) -> Path:
    name = str(manifest["name"])
    template = root / "providers" / "_template"
    destination = root / "providers" / name
    if not template.is_dir():
        raise FileNotFoundError(f"template not found: {template}")
    if destination.exists():
        raise FileExistsError(f"provider already exists: providers/{name}")
    (destination / "logo").mkdir(parents=True)
    (destination / "brand").mkdir()
    (destination / "animations").mkdir()
    shutil.copy2(template / "DESIGN.md", destination / "DESIGN.md")
    shutil.copy2(template / "brand" / "palette.json", destination / "brand" / "palette.json")
    shutil.copy2(template / "logo" / ".gitkeep", destination / "logo" / ".gitkeep")
    (destination / "avo.provider.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    from avo.timeline.provider_animation import ProviderAnimationService
    ProviderAnimationService(
        destination / "animations" / "animation.json",
        provider=name,
    ).initialize()
    return destination

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--kind", choices=VALID_KINDS, default="youtube")
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--sfx", default="")
    parser.add_argument("--music", default="")
    parser.add_argument("--inserts", default="")
    parser.add_argument("--graphics", default="")
    parser.add_argument("--lang", default="en")
    parser.add_argument("--yes", "-y", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = build_manifest(args.name, args.kind, args.raw_root, sfx=args.sfx, music=args.music, inserts=args.inserts, graphics=args.graphics, language=args.lang)
        destination = scaffold_provider(args.root or repo_root(), manifest)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Created provider workspace: {destination}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
