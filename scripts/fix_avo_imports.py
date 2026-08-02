#!/usr/bin/env python3
"""Post-migration fixes for src/avo package."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "avo"

REPO_ROOT_BLOCK = re.compile(
    r"\ndef repo_root\([^)]*\)[^:]*:\n(?:    .+\n)+?(?=\n\n|\ndef |\nclass |\Z)",
    re.MULTILINE,
)


def strip_repo_root(text: str) -> str:
    return REPO_ROOT_BLOCK.sub("\n", text, count=1)


def ensure_paths_import(text: str, extra: str = "") -> str:
    names = ["repo_root"]
    if extra:
        names.extend(x.strip() for x in extra.split(",") if x.strip())
    import_line = f"from avo.paths import {', '.join(dict.fromkeys(names))}"
    if import_line in text:
        return text
    # insert after module docstring / future imports
    lines = text.splitlines(keepends=True)
    insert_at = 0
    if lines and lines[0].startswith('"""'):
        for i, line in enumerate(lines[1:], 1):
            if line.strip().endswith('"""'):
                insert_at = i + 1
                break
    while insert_at < len(lines) and (
        lines[insert_at].startswith("from __future__") or lines[insert_at].strip() == ""
    ):
        insert_at += 1
    lines.insert(insert_at, import_line + "\n")
    return "".join(lines)


def fix_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    original = text
    if path.name == "paths.py":
        return
    text = re.sub(r"\bfrom helpers\.", "from avo.", text)
    text = re.sub(r"\bimport helpers\.", "import avo.", text)
    for mod in ("telemetry", "session", "avo_state", "project_inventory", "wrap", "stats", "render"):
        text = re.sub(rf"^from {mod} import ", rf"from avo.{mod} import ", text, flags=re.M)
    text = text.replace("import helpers.avo_state", "import avo.avo_state")
    if "def repo_root(" in text:
        text = strip_repo_root(text)
        extra = ""
        if path.name in {"validate_dependencies.py", "validate_usability.py", "models.py", "stats.py", "init_project.py"}:
            extra = "config_path"
        if path.name == "init_project.py":
            extra = "config_path, providers_dir"
        if path.name == "validate_edl.py" or path.name == "render.py":
            extra = "schema_path"
        text = ensure_paths_import(text, extra)
    if path.name == "validate_edl.py" and "DEFAULT_SCHEMA" in text:
        text = re.sub(
            r"DEFAULT_SCHEMA = \(.*?edl\.schema\.json\"\)",
            'DEFAULT_SCHEMA = schema_path("edl.schema.json")',
            text,
            flags=re.DOTALL,
        )
        if "schema_path" not in text.split("from avo.paths")[1][:80] if "from avo.paths" in text else True:
            text = ensure_paths_import(text, "schema_path")
    if text != original:
        path.write_text(text, encoding="utf-8")


def main() -> None:
    for path in SRC.rglob("*.py"):
        fix_file(path)
    print("post-migration fixes applied")


if __name__ == "__main__":
    main()
