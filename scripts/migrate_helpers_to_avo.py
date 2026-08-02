#!/usr/bin/env python3
"""Migrate helpers/*.py -> src/avo/ and write compatibility shims."""

from __future__ import annotations

import re
import shutil
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "helpers"
SRC = ROOT / "src" / "avo"
SKIP_SHIM = {"telemetry.mjs"}


def copy_modules() -> list[Path]:
    copied: list[Path] = []
    for src in HELPERS.rglob("*.py"):
        rel = src.relative_to(HELPERS)
        if rel.parts[0] == "__pycache__":
            continue
        dest = SRC / rel
        if dest.name in {"paths.py"} and dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(dest)
    return copied


def rewrite_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\bfrom helpers\.", "from avo.", text)
    text = re.sub(r"\bimport helpers\.", "import avo.", text)
    for mod in (
        "telemetry",
        "session",
        "avo_state",
        "project_inventory",
        "wrap",
        "stats",
    ):
        text = re.sub(rf"^from {mod} import ", rf"from avo.{mod} import ", text, flags=re.M)
    text = text.replace(
        'import helpers.avo_state; print',
        'import avo.avo_state; print',
    )
    text = text.replace("python helpers/", "python -m avo.")
    path.write_text(text, encoding="utf-8")


def avo_module_name(rel: Path) -> str:
    parts = list(rel.with_suffix("").parts)
    return "avo." + ".".join(parts)


def write_shim(rel: Path) -> None:
    avo_mod = avo_module_name(rel)
    helper_path = str(rel).replace("\\", "/")
    content = textwrap.dedent(
        f'''\
        """Compatibility shim — remove in v0.2.0. Use `{avo_mod}`."""
        import warnings

        warnings.warn(
            "helpers.{helper_path} is deprecated; use {avo_mod}",
            DeprecationWarning,
            stacklevel=2,
        )
        from {avo_mod} import *  # noqa: F403
        '''
    )
    (HELPERS / rel).write_text(content, encoding="utf-8")


def main() -> None:
    copied = copy_modules()
    for path in SRC.rglob("*.py"):
        if path.name == "paths.py":
            continue
        rewrite_file(path)
    for src in HELPERS.rglob("*.py"):
        rel = src.relative_to(HELPERS)
        if rel.suffix != ".py":
            continue
        write_shim(rel)
    print(f"copied={len(copied)} shims={len(list(HELPERS.rglob('*.py')))}")


if __name__ == "__main__":
    main()
